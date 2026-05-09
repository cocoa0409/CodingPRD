# Copyright Licensing Trading Platform API — Product Requirements Document

## 1. Introduction

The Copyright Licensing Trading Platform exists to serve a market that today is brokered by paper, fax, and ad-hoc spreadsheets — a market in which the people who own creative works and the people who would like to license them spend most of their effort proving who owns what, negotiating who may use what, and reconciling who paid what. The platform consolidates these flows behind one consistent API: rights holders register works and submit ownership proof, counterparties exchange offers and counter-offers clause by clause, signed contracts move into effect on a precise effective date, royalties are calculated from reported revenue with advances and minimum guarantees applied in a deterministic order, and infringement disputes flow through ownership re-verification, response, escalation, takedown, and resolution.

A second goal sits behind the first: every change of substance must leave a defensible trail. Licenses cannot silently overlap on territory, term, and media when one of them is exclusive; royalty statements cannot be paid for amounts that disagree with what was earned; signatures cannot be applied out of the order the parties agreed to; and reversed payments cannot leave the advance-recoupment ledger drifted from its true position. The platform is therefore designed around event-driven synchronization with payment processors, electronic-signature providers, the copyright authority, and content-distribution platforms — and around a comprehensive audit log that records every license change, contract amendment, dispute step, royalty reversal, and rights-conflict warning. The API surface described in this document is the contract by which all of these guarantees are exposed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly to every endpoint. Domain-specific business behavior is described in §3; cross-cutting concerns live here.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` to identify the acting principal and `X-User-Role` to declare its operational capacity. Requests missing either header are rejected with `ERR_UNAUTHENTICATED`. When the caller's role is not permitted for the targeted endpoint per the role matrix in §4, the server responds with `ERR_FORBIDDEN`. The single exception to the authentication requirement is the public rights-chain history read, which may be served without headers; every other endpoint, including reads, requires both headers.

The platform recognizes two roles, exactly spelled `RightsHolder` and `PlatformAdmin`. When `X-User-Role` is `RightsHolder`, `X-User-ID` is the `id` of the acting `RightsHolder`; ownership checks on any resource that references a `RightsHolder` (such as a `Work`'s `primary_owner_id`, a `License`'s `licensor_id` or `licensee_id`, an `InfringementCase`'s `reporter_id` or `alleged_infringer_id`, or a `Signature`'s `signer_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, in an `AuditLog` `actor_id` written by an admin-driven transition) but does not compare it to any entity's `id`. A `PlatformAdmin` therefore cannot pose as a `RightsHolder` in ownership checks, and a `RightsHolder` cannot exercise admin-only capabilities such as event injection, clock advance, ownership re-verification, or audit-log reads.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept `limit` and `offset` as query-string parameters. The `limit` parameter governs the maximum number of items returned in a single page; it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter governs how many items are skipped before the first returned item; it defaults to 0. Unless a specific endpoint states otherwise, list endpoints return rows sorted by their `created_at` timestamp in ascending order. Every list response embeds `limit`, `offset`, `total_count`, and `has_more` in the response envelope's `meta` object.

### 2.4. Common Resource Properties

Top-level resources — `Work`, `RightsHolder`, `License`, `Contract`, `RoyaltyStatement`, `InfringementCase` — carry four system-managed fields: `id` is a server-minted UUID with no type prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `version` is an integer that begins at 1 on creation and increments by exactly one on every mutation that changes any field of the resource. Sub-resources whose lifecycle is purely append-only — namely `NegotiationRound`, `Signature`, `RightsChainEvent`, `ExternalEvent`, and `AuditLog` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from these entities because they are never modified after insertion.

Server-set fields are populated by the server on the relevant transition and remain `null` until then: a `Work`'s `certificate_id` and `certificate_issued_at` are `null` until the work transitions into `REGISTERED`; a `License`'s `pinned_work_version` is `null` until the license transitions into `ACCEPTED`; a `License`'s `contract_id` and `effective_date` are `null` until those transitions occur; a `Contract`'s `fully_signed_at` is `null` until the last required signer signs; an `InfringementCase`'s `takedown_issued_at` is `null` until escalation, `compensation_cents` is `null` until resolution, and `pinned_certificate_id` is `null` until ownership has been verified. Counters such as a `License`'s `current_round`, `cumulative_advance_recouped_cents`, and a `Contract`'s `signed_count`, and a `Work`'s `rights_chain_event_count` are server-maintained and reflect the live count or sum at read time.

### 2.5. Hierarchical Consistency and Cascading Effects

When the server mutates an entity in the course of executing a transition, every field that changed counts as a mutation: `updated_at` is refreshed and `version` is incremented by one. This applies whether the mutation was directly requested by the client or was a side effect of another transition. When a single operation cascades across more than one entity — for example, a takedown that terminates licenses, terminates their contracts, and bars future payments on their draft statements — every entity touched along the cascade has its own `updated_at` and `version` advanced independently. The chronological narrative of every mutation that changes substantive state is captured in an `AuditLog` row whose `before` and `after` snapshots record the relevant fields, plus a `change_type` drawn from the catalog `LICENSE_CHANGED`, `CONTRACT_AMENDED`, `DISPUTE_LOGGED`, `ROYALTY_REVERSED`, and `RIGHTS_CONFLICT_DETECTED`. Every audit row also carries the `actor_id` (a `RightsHolder` `id` or the literal string `system` for auto-transitions) and the `subject_entity` and `subject_id` of the mutated row.

Transitions that the server fires automatically on behalf of the client — a `License` advancing from `ACCEPTED` to `SIGNED` when its `Contract` reaches `FULLY_SIGNED`, the joint advance of `License` and `Contract` to `EFFECTIVE` when the clock crosses the effective-date target, the advance of an `EFFECTIVE` `License` to `EXPIRED` when the clock reaches `term_end` — all run as compensating side effects of the operation that triggered them. They mutate `updated_at` and `version` on each entity they touch and write their own `AuditLog` rows, just as if the client had issued the transition directly.

### 2.6. Nested Resource Validation Order

Several endpoints carry more than one path identifier — listing the rounds of a license, fetching a royalty statement nested under its license, working through any of the seven infringement-case lifecycle endpoints. For every such request the server validates path identifiers strictly left-to-right: if the first identifier does not resolve to a live entity the server responds with `ERR_NOT_FOUND` for that identifier without attempting the second; only after the parent resolves does the server attempt to resolve the child. This ordered resolution is one of the priority-3 path-existence checks described in §2.10.

### 2.7. Optimistic Concurrency Control

Any endpoint that mutates a specific resource accepts an optional `version` field in its request body. When `version` is supplied it must equal the resource's current `version`; if the supplied value disagrees with the stored value the server rejects the request with `ERR_VERSION_MISMATCH`. Omitting `version` skips the concurrency check entirely — the mutation proceeds without any version comparison — and is the appropriate behavior when the client has no opinion about staleness. Successful mutations always increment `version` by one regardless of whether the client supplied the field. PATCH endpoints and the various state-transition endpoints all honor this rule.

### 2.8. Monetary Precision and Rounding

All monetary values in the platform are expressed and stored as integer cents — `fixed_fee_cents`, `minimum_guarantee_cents`, `advance_cents`, `gross_revenue_cents`, `earned_royalty_cents`, `advance_recouped_cents`, `net_payable_cents`, `cumulative_advance_recouped_cents`, `compensation_cents`, and `refund_cents`. Royalty share calculations that produce a fractional cent are rounded half-up to the nearest whole cent. Ownership shares use integer basis points, where 10000 basis points represents 100% of the work; values below 10000 represent the corresponding decimal percentage. Revenue-share percentages on a license are also expressed in basis points: `revenue_share_bps` of 0 means no revenue is shared and `revenue_share_bps` of 10000 means 100% of revenue is paid as royalty.

### 2.9. Date Semantics, Term Intervals, and the Effective Date

Every datetime in this API is an ISO 8601 UTC string with three fractional digits. License terms are expressed by `term_start` and `term_end`; the effective interval is half-open with the lower bound inclusive and the upper bound exclusive — that is, `term_start` is the first instant the license can be effective and `term_end` is the first instant it is no longer effective. Two terms touching at a single instant therefore do not overlap. Date comparisons used by the rights-conflict check operate at second granularity in UTC.

The effective date of a license is the later of the contract's `effective_date_target` and the license's `term_start`; the system advances the license to `EFFECTIVE` at the moment the wall clock reaches that later instant, with the boundary inclusive (the instant the clock equals the candidate, the transition fires). Until that moment, a license whose contract is `FULLY_SIGNED` remains in `SIGNED` with `effective_date` unset; once fired, `effective_date` is set to that later instant.

### 2.10. Validation Priority Ordering

When an endpoint has multiple things that could go wrong with a single request, the server evaluates them in a fixed order so that failures are reported in a predictable sequence. The order is:

1. Authentication — both `X-User-ID` and `X-User-Role` headers must be present, otherwise `ERR_UNAUTHENTICATED`.
2. Authorization — the caller's role must be permitted for the endpoint, otherwise `ERR_FORBIDDEN`.
3. Path existence — every path-parameter id must resolve to a live entity, validated left-to-right per §2.6, otherwise `ERR_NOT_FOUND`.
4. Optimistic concurrency — when `version` is supplied in the body it must match the stored version, otherwise `ERR_VERSION_MISMATCH`.
5. State eligibility — the resource must be in a state from which the requested transition is legal, otherwise `ERR_INVALID_STATE`.
6. Business referential integrity — cross-entity foreign keys must resolve and refer to a party authorized for the role they are taking (for example, a `licensor_id` that is the work's primary owner or co-owner), otherwise `ERR_FORBIDDEN`. This check applies in particular to license creation and infringement-case creation.
7. Business safety — the rights-conflict check must not raise an exclusive-license violation on license acceptance, otherwise `ERR_EXCLUSIVE_LICENSE_VIOLATION`. This applies to accepting a negotiation round.
8. Business temporal — territory or term overlap that is not blocked by exclusivity may still surface as `ERR_TERRITORY_TERM_OVERLAP` when both candidate and incumbent are exclusive on the relevant slice; non-exclusive overlaps are non-blocking but raise an audit warning. This also applies on accept.
9. Business constraint — negotiation turn alternation (`ERR_NOT_YOUR_TURN`) on round submission.
10. Signing order (`ERR_SIGNATURE_OUT_OF_ORDER`) on signature submission.
11. Duplicate signature (`ERR_DUPLICATE_SIGNATURE`) on signature submission.
12. Co-owner uniqueness (`ERR_DUPLICATE_CO_OWNER`) on work creation and patch.
13. Ownership shares total (`ERR_OWNERSHIP_SHARES_INVALID`) on work creation and patch.
14. Payment amount equality (`ERR_PAYMENT_AMOUNT_MISMATCH`) on payment-received and payment-refunded events.
15. Effective-date-within-term (`ERR_EFFECTIVE_DATE_OUT_OF_TERM`) on contract creation.
16. Royalty-period boundaries (`ERR_INVALID_PERIOD`) on royalty statement creation.
17. Reversal pointer validity (`ERR_INVALID_REVERSAL`) on reversal entry creation.
18. Pinned-version freshness (`ERR_PINNED_VERSION_STALE`) on the auto-transition into `SIGNED`.
19. Pinned-certificate freshness (`ERR_PINNED_CERTIFICATE_STALE`) on `respond` for an infringement case.
20. External-event idempotency (`ERR_DUPLICATE_EXTERNAL_EVENT`) on event injection.
21. Evidence non-empty (`ERR_EVIDENCE_MISSING`) on infringement-case creation and verify-ownership.
22. Compensation non-negative (`ERR_COMPENSATION_INVALID`) on resolve.
23. Term well-formedness (`ERR_INVALID_TERM`) on license creation and patch.

Lower-numbered checks short-circuit higher-numbered ones — a request missing both authentication and a path id surfaces as `ERR_UNAUTHENTICATED`, never `ERR_NOT_FOUND`; a request with a state error and a payload-amount mismatch surfaces as `ERR_INVALID_STATE`, never `ERR_PAYMENT_AMOUNT_MISMATCH`.

### 2.11. External Event Synchronization and Idempotency

The platform is event-driven: payment processors, electronic-signature providers, the copyright authority, and content-distribution platforms all reach the system through a single ingestion endpoint that accepts an `ExternalEvent`. Each event names its `source` (one of `PAYMENT`, `E_SIGN`, `COPYRIGHT_AUTHORITY`, or `DISTRIBUTION_PLATFORM`), its `event_type` (one of `PAYMENT_RECEIVED`, `PAYMENT_REFUNDED`, `SIGNATURE_VERIFIED`, `SIGNATURE_REJECTED`, `REGISTRATION_APPROVED`, `REGISTRATION_REJECTED`, `TAKEDOWN_ACKED`, `DISTRIBUTION_REVENUE_REPORTED`), its `ref_entity` and `ref_id` (the targeted row), a source-specific `payload` (for example, `{amount_cents, currency}` for a `PAYMENT_RECEIVED`), and an `external_event_id` chosen by the upstream system. The pair `(source, external_event_id)` must be unique; resubmitting an event with a `(source, external_event_id)` that already exists with a different payload is rejected with `ERR_DUPLICATE_EXTERNAL_EVENT`, while a byte-equal replay returns the original outcome and does not re-run side effects. The server stores `applied` and `applied_at` to record whether the event has been processed and when.

### 2.12. Concurrency Resolution

Several pairs of operations may race in production; in every such case the server serializes them on a single point and the loser receives a specific error code so that callers can diagnose what happened. Two parties simultaneously submitting a `NegotiationRound` on the same license serialize on the increment of `current_round`: the first writer wins, and the second's submission is rejected with `ERR_NOT_YOUR_TURN` because, after the first writer increments the counter, the second is no longer the opposite party. Two signers concurrently submitting signatures for the same contract serialize on the increment of `signed_count`: the first writer wins, the second is rejected with `ERR_SIGNATURE_OUT_OF_ORDER`. Two payment events arriving with the same `external_event_id` for the same royalty statement serialize on the uniqueness of `(source, external_event_id)`: the first applies side effects, and a payload-disagreeing replay is rejected with `ERR_DUPLICATE_EXTERNAL_EVENT`. Two clients calling accept on competing licenses while a third creates a conflicting effective license serialize on a re-evaluation of the rights-conflict check inside the same transaction that flips status to `ACCEPTED`: at most one license can become `ACCEPTED` for the conflicting territory/term/media slice, and the second loser receives `ERR_EXCLUSIVE_LICENSE_VIOLATION`. Manual termination racing with a payment event for one of the license's `DRAFT` statements serializes on the license's status: either termination wins (the statement stays `DRAFT`, and the payment event is rejected with `ERR_LICENSE_NOT_EFFECTIVE`) or the settlement wins (the license stays `EFFECTIVE` because of the pending settlement, and the termination is rejected with `ERR_HAS_PENDING_SETTLEMENTS`).

## 3. Business Logic & Workflows

### 3.1. Onboarding Rights Holders and Drafting a Work

Before any rights can be traded, the parties must be visible to the platform. A new `RightsHolder` is created by submitting a `legal_name`, a `holder_type` of either `INDIVIDUAL` or `ENTITY`, a `contact_email`, and a `jurisdiction` expressed as the ISO 3166-1 alpha-2 code of the holder's legal residence. Both administrators and rights holders themselves can perform this onboarding; the resource that comes back carries the `id` that future requests will use to claim ownership, propose licenses, and sign contracts.

A registered holder can then begin a work in `DRAFT`. Drafting a `Work` requires a `title`, a `work_type` drawn from the enumeration `LITERARY`, `MUSIC`, `FILM`, `SOFTWARE`, `ARTWORK`, a `creation_date` (the original date the work was created, expressed as an ISO 8601 UTC timestamp), the `primary_owner_id` of the holder claiming primary ownership, the share that primary owner holds expressed as `primary_share_bps` integer basis points, an array of `co_owners` each shaped as `{rights_holder_id, share_bps}`, and an `ownership_proof_doc_id` referring to a previously uploaded proof document. The work's `registration_status` begins at `DRAFT`; its `certificate_id`, `certificate_issued_at`, and `pinned_work_version` (the latter belongs to derived licenses, not the work itself) all start unset. While the work is in `DRAFT`, the primary owner — and only the primary owner — may patch the `title`, the `co_owners` array, the `primary_share_bps`, and the `ownership_proof_doc_id`. Attempts to patch by anyone whose `X-User-ID` is not the work's `primary_owner_id` are rejected with `ERR_FORBIDDEN`. Every accepted patch writes an `AuditLog` row of `change_type` `LICENSE_CHANGED` recording the diff, refreshes `updated_at`, and increments `version`.

Whether at creation or in a patch, the ownership shares must form a valid distribution: the sum of `primary_share_bps` and every `share_bps` in `co_owners` must equal exactly 10000 basis points; every individual `share_bps` must be strictly greater than zero and at most 10000; and no `rights_holder_id` may appear more than once in `co_owners`. A duplicated co-owner is rejected with `ERR_DUPLICATE_CO_OWNER`; a basis-point sum that is not exactly 10000, or any individual share that is zero, negative, or greater than 10000, is rejected with `ERR_OWNERSHIP_SHARES_INVALID`. The duplicate-co-owner check evaluates before the share-total check so that a request that contains both errors surfaces the duplication first.

### 3.2. Submitting for Registration and Recording the Rights Chain

When the holder is satisfied with the draft, submission moves the work to `UNDER_REVIEW`, transitioning `registration_status` from `DRAFT` to `UNDER_REVIEW`. Submission has two preconditions: the share distribution must still be valid (`primary_share_bps` plus the sum of `co_owners`'s `share_bps` equal to 10000; `ERR_OWNERSHIP_SHARES_INVALID` otherwise) and `ownership_proof_doc_id` must be non-empty (`ERR_OWNERSHIP_PROOF_MISSING` otherwise). The submit call is gated by the standard optimistic-concurrency rule: a `version` may be supplied to detect stale data.

Registration itself is granted by the copyright authority, which is modeled as an external system that emits an event with `source` of `COPYRIGHT_AUTHORITY` and `event_type` of either `REGISTRATION_APPROVED` or `REGISTRATION_REJECTED`, each pointing at the work via `ref_id`. An approval transitions the work from `UNDER_REVIEW` to `REGISTERED`; the server mints a fresh UUID for `certificate_id`, stamps `certificate_issued_at` with the current instant, and appends a `RightsChainEvent` with `event_type` of `REGISTERED`, `ref_entity` of `Work`, and `ref_id` set to the work's `id`. A rejection transitions the work from `UNDER_REVIEW` to `REJECTED`, which is terminal and produces no certificate. Both transitions require the work to actually be in `UNDER_REVIEW` at the moment the event is applied; an event arriving for a work in any other state is rejected with `ERR_INVALID_STATE`.

The full lineage of a work — its registration, every license signed against it, every license terminated, every infringement case resolved, and any ownership transfer — is preserved in a chain of `RightsChainEvent` rows. Each event carries the `work_id` it belongs to, an `event_type` chosen from `REGISTERED`, `LICENSE_SIGNED`, `LICENSE_TERMINATED`, `INFRINGEMENT_RESOLVED`, and `OWNERSHIP_TRANSFERRED`, an `actor_id` that is either a `RightsHolder` `id` or the literal string `system`, a `ref_entity` naming the type of the referenced entity (`License`, `Contract`, `InfringementCase`, or `Work`), the `ref_id` of that entity, and a `payload` snapshot of the relevant fields at the moment of the event. The work itself surfaces a `rights_chain_event_count` derived from the count of rows pointing at it. Reading the chain is the only operation in the API that does not require authentication headers: the rights-chain history of a registered work is a public artifact that anyone can fetch, paginated through `limit` and `offset`.

### 3.3. Negotiating a License: Offers, Counters, and Acceptance

A licensor begins a deal by drafting a `License` against a registered work. The licensor names the `work_id`, themselves as `licensor_id`, the counterparty as `licensee_id` (which must be a different `RightsHolder` from the licensor), the `territory` as a non-empty array of ISO 3166-1 alpha-2 country codes — with the special token `WORLD` exclusive of all other codes (a territory containing `WORLD` may not also contain a specific country) — the `term_start` and `term_end` UTC datetimes that bound the license, the `media_types` as a non-empty subset of `DIGITAL`, `PRINT`, `BROADCAST`, and `MERCHANDISE`, an `exclusivity` of either `EXCLUSIVE` or `NON_EXCLUSIVE`, a `sublicense_allowed` boolean controlling whether the licensee may sublicense the rights downstream, a `revision_rights` of `NONE`, `MINOR`, or `FULL` controlling derivative-work permissions, the financial terms (`fixed_fee_cents`, `revenue_share_bps`, `minimum_guarantee_cents`, and `advance_cents`), and a `settlement_period` of `MONTHLY`, `QUARTERLY`, or `ANNUAL`. The license is created with `status` of `OFFERED` and `current_round` of 1; the server simultaneously persists a first `NegotiationRound` row whose `round_number` is 1, whose `action` is `OFFER`, and whose `proposed_by_id` is the licensor. The license must respect `term_start` strictly before `term_end`, and `term_start` must lie in the future relative to the moment of creation; otherwise the server returns `ERR_INVALID_TERM`. The licensor is required, by referential check, to be either the work's `primary_owner_id` or one of the holders in `co_owners`; if the caller is neither, the request is rejected with `ERR_FORBIDDEN`.

From `OFFERED`, the parties iterate. A counter-offer is a `NegotiationRound` with `action` of `COUNTER`, `proposed_by_id` set to the calling holder, and a `clause_diff` whose keys are the `License` field names being changed and whose values are objects of the shape `{old, new}` pinned at submission time. A counter advances the license to `COUNTERED`, increments `current_round` by exactly one, persists the round (server-stamping the round's `submitted_at`), and writes an `AuditLog` of `change_type` `LICENSE_CHANGED`. A second counter from `COUNTERED` follows the same rule: another `NegotiationRound`, another increment of `current_round`, another audit row, with the license remaining in `COUNTERED`. The hard rule across all counters is turn alternation: the caller must be the *opposite* party from whoever submitted the previous round, where the opposite of the licensor is the licensee and vice versa. A caller who is the same party as the previous round's `proposed_by_id` is rejected with `ERR_NOT_YOUR_TURN`. A caller who is neither the licensor nor the licensee is rejected with `ERR_FORBIDDEN` before the turn check runs.

Acceptance is also a `NegotiationRound`, with `action` of `ACCEPT`. From `OFFERED` to `ACCEPTED`, the licensee is the one who accepts; the caller must therefore be the `licensee_id` (otherwise `ERR_NOT_YOUR_TURN`). From `COUNTERED` to `ACCEPTED`, the caller must again be the opposite party from whoever submitted the most recent round. Independently, the work must currently be in `REGISTERED` (any other state yields `ERR_WORK_NOT_REGISTERED`) and the rights-conflict check described in §3.4 must produce no blocking conflicts — failure on the exclusivity arm yields `ERR_EXCLUSIVE_LICENSE_VIOLATION` and the territory-term overlap arm yields `ERR_TERRITORY_TERM_OVERLAP`. On a successful accept the server captures the work's current `version` into the license's `pinned_work_version`, persists the accepting `NegotiationRound`, and writes an `AuditLog` of `LICENSE_CHANGED`.

A licensor may pull an open offer back at any time before acceptance. A `NegotiationRound` with `action` of `WITHDRAW` from `OFFERED` or `COUNTERED` transitions the license to the terminal `WITHDRAWN` state and writes an `AuditLog`. Withdraw is restricted to the licensor (`ERR_FORBIDDEN` otherwise). All round submissions accept an optional `version` for OCC. The `clause_diff` field is required on counters and is pinned, so that subsequent reads of the negotiation history reproduce exactly what each side proposed at each step. Negotiation history is enumerated in chronological order through the rounds-list endpoint; the same endpoint accepts the standard `limit` and `offset` query parameters.

### 3.4. Detecting Rights Conflicts

The rights-conflict check is the single most consequential business rule on the platform: it runs at every license status check during rounds and again, decisively, at the moment a license advances from `OFFERED` or `COUNTERED` to `ACCEPTED`. The check operates on every other license belonging to the same work whose `status` is among `ACCEPTED`, `SIGNED`, or `EFFECTIVE` (a license in `SIGNED` before its effective date counts as part of the input set; one in `OFFERED`, `COUNTERED`, `WITHDRAWN`, `EXPIRED`, or `TERMINATED` does not).

For each candidate-incumbent pair, the server computes three overlaps. Territory overlap is true when the intersection of the two territory arrays is non-empty, or when either side's territory contains the token `WORLD`. Media overlap is true when the intersection of the two `media_types` arrays is non-empty. Term overlap uses half-open interval semantics with the lower bound inclusive and the upper bound exclusive: the two terms overlap when the incumbent's `term_start` is strictly less than the candidate's `term_end` and, simultaneously, the candidate's `term_start` is strictly less than the incumbent's `term_end`. Adjacency — where one term ends at the same instant the other begins — therefore does not constitute overlap. A pair is in conflict if and only if territory overlap and media overlap and term overlap all hold; pairs with mismatched `work_id` or with an incumbent in a non-relevant status are not considered. Date comparisons are performed at second granularity in UTC.

From the set of conflicting pairs the server derives the outcome. If there exists at least one incumbent license whose `exclusivity` is `EXCLUSIVE` and which conflicts with the candidate, the candidate cannot be accepted and the server raises `ERR_EXCLUSIVE_LICENSE_VIOLATION` — an exclusive incumbent blocks anyone else on the overlapping slice. Symmetrically, if the candidate's own `exclusivity` is `EXCLUSIVE` and any other license at all conflicts with it, the candidate is again rejected with `ERR_EXCLUSIVE_LICENSE_VIOLATION` — an exclusive candidate cannot enter a slice that anyone else is already on. If neither the candidate nor any conflicting incumbent is exclusive (both are `NON_EXCLUSIVE`), the conflict is allowed but is not silent: the server appends an `AuditLog` row of `change_type` `RIGHTS_CONFLICT_DETECTED` whose `before` is null and whose `after` snapshots the candidate license, then permits the acceptance. The `ERR_TERRITORY_TERM_OVERLAP` code is reserved for the narrow case of two `EXCLUSIVE` candidates racing into the same slice and is otherwise non-blocking.

This check is also the serialization point for the concurrency race described in §2.12: the rights-conflict check is re-evaluated inside the same transaction that flips the license's status to `ACCEPTED`, so two clients accepting competing licenses cannot both succeed.

### 3.5. From Acceptance to Contract: Drafting and Signing

Acceptance does not bind the parties — the binding instrument is the `Contract`. From an `ACCEPTED` license, any participant can create a primary contract by submitting the `license_id` (which must currently be in `ACCEPTED`, otherwise `ERR_LICENSE_NOT_ACCEPTED`), an ordered `signing_order` array of `RightsHolder` `id`s defining who signs first, second, and so on, and an `effective_date_target` UTC timestamp. The target effective date must satisfy `term_start <= effective_date_target` and `effective_date_target < term_end` of the underlying license (the lower bound inclusive, the upper bound exclusive); a target outside this half-open interval is rejected with `ERR_EFFECTIVE_DATE_OUT_OF_TERM`. A supplementary agreement is created the same way but supplies `parent_contract_id` pointing at the contract being supplemented; the parent must be `EFFECTIVE` to be supplemented (any other state yields `ERR_INVALID_STATE` per §2.10). For a primary contract, `parent_contract_id` is null. The new contract begins in `PENDING_SIGNATURES` with `signed_count` of 0 and `fully_signed_at` unset.

Signatures are then applied one at a time by the holders named in `signing_order`. Each call carries the `signer_id` of the signing holder, an opaque `signature_payload` (e.g., a base64-encoded electronic-signature blob), and an optional `version` for OCC. Three checks gate every submission. First, the underlying `License.status` must be `ACCEPTED` at the moment the signature is applied; if the license has slipped out of `ACCEPTED` for any reason, the request is rejected with `ERR_LICENSE_NOT_ACCEPTED`. Second, `signer_id` must equal the element of `signing_order` at the index `signed_count` (treating `signing_order` as 0-indexed) — that is, the contract demands signers in the exact order they were listed, and any mismatch is rejected with `ERR_SIGNATURE_OUT_OF_ORDER`. Third, the same `signer_id` must not already have a `Signature` on this contract; a repeat is rejected with `ERR_DUPLICATE_SIGNATURE`. On success the server persists the `Signature` (server-stamping `signed_at`), increments `signed_count` by exactly one, and refreshes the contract.

When `signed_count` reaches `len(signing_order)` — that is, the last required signer has just signed — the server auto-transitions the contract from `PENDING_SIGNATURES` to `FULLY_SIGNED`, sets `fully_signed_at` to the current instant, writes an `AuditLog` of `CONTRACT_AMENDED`, and propagates the cascade to the underlying license: the `License.status` advances from `ACCEPTED` to `SIGNED`, with two preconditions of its own — the license's `contract_id` must be set (it is, because the cascading contract is the one carrying that license), and the work's current `version` must still equal the license's `pinned_work_version`. If the work has been mutated since acceptance (so that the pinned version no longer matches), the auto-transition fails with `ERR_PINNED_VERSION_STALE`. The license's transition into `SIGNED` writes another `AuditLog` of `CONTRACT_AMENDED` and appends a `RightsChainEvent` of `event_type` `LICENSE_SIGNED` with `ref_entity` of `License` and `ref_id` set to the license's `id`.

### 3.6. The Effective Date and the Lifecycle of an Effective License

A `SIGNED` license has not yet begun. The platform models the time gap between fully-signed and effective explicitly: the candidate effective instant is the later of `Contract.effective_date_target` and `License.term_start` (max of the two), and the system advances the license to `EFFECTIVE` only when the wall clock reaches that candidate, with the boundary inclusive — at the precise instant the clock equals the candidate, the transition fires. Before that instant the license stays `SIGNED` and `effective_date` remains unset; at the instant, `effective_date` is set to that candidate value, the contract advances jointly from `FULLY_SIGNED` to `EFFECTIVE`, and the license is now in force. Both the license and the contract have their `updated_at` and `version` advanced. The clock-advance capability (an admin-only test-driving capability that advances the logical clock to a supplied `to_iso8601` instant) is what fires this transition in the test environment; in production the same evaluation runs continuously.

An `EFFECTIVE` license can leave that state in three ways. Two are involuntary: when the clock crosses `term_end`, the license auto-advances from `EFFECTIVE` to `EXPIRED` (terminal), appending a `RightsChainEvent` of `LICENSE_TERMINATED` whose `payload` records the reason as `EXPIRED`. The third is voluntary: a manual termination by the licensor, which transitions the license from `EFFECTIVE` to `TERMINATED` (also terminal). Manual termination is restricted to the `licensor_id` (`ERR_FORBIDDEN` otherwise), and may proceed only when every `RoyaltyStatement` for the license is in one of `SETTLED`, `REVERSED`, or `DRAFT` — meaning there are no in-flight payment events for `DRAFT` statements. A pending settlement blocks termination with `ERR_HAS_PENDING_SETTLEMENTS`. On success the server writes an `AuditLog` of `LICENSE_CHANGED`, appends a `RightsChainEvent` of `LICENSE_TERMINATED` whose `payload` reason is `MANUAL`, and cascades the underlying contract: any `EFFECTIVE` contract whose `License.status` has just become `TERMINATED` advances itself from `EFFECTIVE` to `TERMINATED`, writing an `AuditLog` of `CONTRACT_AMENDED`.

A separate cascade affects contracts whose role has been replaced rather than ended: when a supplementary contract — one whose `parent_contract_id` points at this contract — itself reaches `FULLY_SIGNED`, the parent contract auto-advances from `EFFECTIVE` to `SUPERSEDED` (terminal), recording an `AuditLog` of `CONTRACT_AMENDED` whose `before` is `status=EFFECTIVE` and `after` is `status=SUPERSEDED`.

### 3.7. Royalty Statements: Calculation, Settlement, and Reversal

Once a license is `EFFECTIVE`, the licensor reports earnings through `RoyaltyStatement` rows. A statement carries the `license_id` (set from the URL), a `period_start_at` (inclusive) and a `period_end_at` (exclusive), the `gross_revenue_cents` reported for the period (a non-negative integer), and a `variant` of either `PROVISIONAL` or `FINAL`. The duration `period_end_at - period_start_at` must align with the license's `settlement_period`: a `MONTHLY` license expects monthly periods, `QUARTERLY` expects quarterly periods, `ANNUAL` expects annual periods, and any misaligned or backwards period (`period_start_at` not strictly less than `period_end_at`) is rejected with `ERR_INVALID_PERIOD`. Statements may only be created when the license's `status` is `EFFECTIVE` at the moment `period_end_at` is read; otherwise the creation is blocked.

The server computes the financial fields in a fixed order. First, the revenue share is the product of `gross_revenue_cents` and the license's `revenue_share_bps`, divided by 10000, rounded half-up to the nearest whole cent. Second, the earned royalty is the maximum of the revenue share and the license's `minimum_guarantee_cents` — that is, the minimum guarantee acts as a floor under the earned amount. Third, the remaining advance is the maximum of zero and the license's `advance_cents` minus its `cumulative_advance_recouped_cents` — once the advance has been fully recouped this remainder cannot go negative. Fourth, the advance recouped on this statement is the lesser of the earned royalty and the remaining advance — the system recovers as much of the outstanding advance as the period earned, but never more. Fifth, the net payable is the earned royalty minus the advance recouped, which is always non-negative because of the previous step. The rounding order is fixed: the revenue share is rounded half-up first, *then* the maximum with the minimum guarantee is taken, *then* the recoupment is subtracted; rounding is not re-applied later. The five fields are persisted as `earned_royalty_cents`, `advance_recouped_cents`, and `net_payable_cents` (the intermediate revenue share and remaining advance are not persisted).

The two variants change how that formula is applied. A `PROVISIONAL` statement is for mid-period reporting; it ignores the minimum guarantee — the provisional net payable is the maximum of zero and the revenue share minus the remaining advance — and a `PROVISIONAL` statement never settles. A `FINAL` statement applies the full formula above, including the maximum with the minimum guarantee, and only `FINAL` statements may transition to `SETTLED`.

Settlement happens when a payment processor emits a `PAYMENT_RECEIVED` event with `source` of `PAYMENT`, `ref_entity` of `RoyaltyStatement`, and `ref_id` equal to the statement's `id`. Two preconditions must hold: the event's `payload.amount_cents` must equal the statement's `net_payable_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH` otherwise), and the underlying license must be in `EFFECTIVE` (`ERR_LICENSE_NOT_EFFECTIVE` otherwise). On success the statement transitions from `DRAFT` to `SETTLED`, `settled_at` is stamped to the current instant, and the license's `cumulative_advance_recouped_cents` is increased by exactly the `advance_recouped_cents` of this statement.

Reversal is the inverse, and is the only operation that may transition a `SETTLED` statement to a terminal `REVERSED`. It is a two-step flow. First, the licensor creates a new `RoyaltyStatement` row whose `reversal_of_id` points at the original `SETTLED` statement and whose `refund_cents` records the refund amount; `reversal_of_id` must resolve to a `SETTLED` statement on the same license, and `refund_cents` must be non-null on a reversal entry (a non-resolving `reversal_of_id` is rejected with `ERR_INVALID_REVERSAL`). Second, a `PAYMENT_REFUNDED` event is emitted, again pointing at the reversal entry; its `payload.amount_cents` must equal the reversal entry's `refund_cents` (otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`), and the original statement must still be in `SETTLED` (otherwise `ERR_INVALID_STATE`). On success the original statement's `status` flips to `REVERSED`, and the license's `cumulative_advance_recouped_cents` is *decreased* by exactly the original statement's `advance_recouped_cents` — the compensating action that exactly cancels the increment performed at original settlement, keeping the running ledger consistent. Every successful settlement and every successful reversal also writes an `AuditLog` row of `change_type` `ROYALTY_REVERSED` for reversals (and `LICENSE_CHANGED` for settlements that affect the license counter).

The advance-recoupment invariant is therefore: at all times, a license's `cumulative_advance_recouped_cents` equals the sum of `advance_recouped_cents` across its `SETTLED` statements, less the sum of the original `advance_recouped_cents` of any `SETTLED` statement that has been paired into a `REVERSED` outcome. Statements may also be filtered when listed by their `status` query parameter (along with `limit` and `offset`).

### 3.8. Infringement: Reporting, Verification, Response, Takedown, Resolution

When a rights holder believes a third party is using their work without authorization, they file an `InfringementCase`. The reporter — who must be the work's `primary_owner_id` or one of its `co_owners`, otherwise `ERR_FORBIDDEN` — submits the `work_id` (which must be `REGISTERED`), the `alleged_infringer_id` of the suspected infringer, and a non-empty array `evidence_doc_ids` of opaque evidence document identifiers (an empty array is rejected with `ERR_EVIDENCE_MISSING`). The case begins in `review_stage` of `REPORTED`, with `pinned_certificate_id`, `takedown_issued_at`, `compensation_cents`, and `response_text` all unset. Creation also writes an `AuditLog` of `change_type` `DISPUTE_LOGGED`. The reporter is recorded as the case's `reporter_id`; the reporter alone may dismiss the case from `REPORTED` to the terminal `DISMISSED` state.

A `PlatformAdmin` then performs ownership verification, advancing `review_stage` from `REPORTED` to `OWNERSHIP_VERIFIED`. This step requires the work to still be `REGISTERED` (`ERR_WORK_NOT_REGISTERED` otherwise) and the case's evidence to remain non-empty (`ERR_EVIDENCE_MISSING` otherwise). On success the server pins the work's current `certificate_id` into the case's `pinned_certificate_id` and writes an `AuditLog` of `DISPUTE_LOGGED`. Pinning the certificate at this step creates a snapshot of the rights chain that downstream steps will check against — the same pattern that pinning the work `version` at acceptance plays for licenses.

The alleged infringer responds next, transitioning the case from `OWNERSHIP_VERIFIED` to `RESPONSE_RECEIVED` by submitting a `response_text`. The caller must be the `alleged_infringer_id` (`ERR_FORBIDDEN` otherwise), and the work's current `certificate_id` must still equal the case's `pinned_certificate_id` — if a re-registration or other rights event has changed the certificate since verification, the response is rejected with `ERR_PINNED_CERTIFICATE_STALE`. The submitted text is persisted into `response_text` and an `AuditLog` of `DISPUTE_LOGGED` is written.

If the reporter is not satisfied with the response, escalation transitions the case from `RESPONSE_RECEIVED` to `UNDER_ARBITRATION`. Escalation is restricted to the `reporter_id`; it stamps `takedown_issued_at` with the current instant — that timestamp is the moment the takedown notice is considered issued — and triggers the takedown cascade described in the next paragraph. From `UNDER_ARBITRATION` the case has two terminal exits: `RESOLVED` and `DISMISSED`. Resolution by the reporter sets a non-negative `compensation_cents` (a missing or negative value is rejected with `ERR_COMPENSATION_INVALID`), appends a `RightsChainEvent` of `event_type` `INFRINGEMENT_RESOLVED` whose `payload` carries the compensation amount, and writes an `AuditLog` of `DISPUTE_LOGGED`. Dismissal from `UNDER_ARBITRATION` is also reporter-only and writes an audit row of the same `change_type`.

The takedown cascade fires on the escalation transition. For every `EFFECTIVE` license whose `work_id` equals the case's `work_id` and whose `licensee_id` equals the case's `alleged_infringer_id`, the server flips the license's `status` to `TERMINATED` and appends a `RightsChainEvent` of `LICENSE_TERMINATED` whose `payload.reason` is `TAKEDOWN` and whose `payload` carries the `case_id`. Then, for every `EFFECTIVE` `Contract` whose `license_id` is that license's `id`, the server flips the contract's `status` to `TERMINATED` and writes an `AuditLog` of `CONTRACT_AMENDED`. Any `DRAFT` `RoyaltyStatement` that belongs to such a license remains `DRAFT` — only `SETTLED` statements ever flip to `REVERSED`, and a takedown does not retroactively reverse settled royalties — but future `PAYMENT_RECEIVED` events for those `DRAFT` statements will be rejected with `ERR_LICENSE_NOT_EFFECTIVE` because the license is no longer effective. The cascade is ordered: licenses first, then their contracts; an `AuditLog` row is appended at each hop of the cascade, including the case's own `DISPUTE_LOGGED` entry for the escalation.

### 3.9. Audit Logs and Public Rights-Chain History

A `PlatformAdmin` is the consumer of the `AuditLog` index. Each audit row carries an `actor_id`, a `subject_entity` and `subject_id` naming the specific resource that was mutated, a `change_type` (`LICENSE_CHANGED`, `CONTRACT_AMENDED`, `DISPUTE_LOGGED`, `ROYALTY_REVERSED`, or `RIGHTS_CONFLICT_DETECTED`), and `before` and `after` snapshots of the relevant fields. The audit index is filterable by `subject_entity`, `subject_id`, and `change_type`, and accepts the standard `limit` and `offset` pagination. Combined with the rights-chain history (which is publicly readable, paginated by `limit` and `offset`), these two streams together constitute the platform's compliance trail: the audit log is the operational record of every change of consequence, while the rights-chain is the public-facing lineage of a work and its licensees.

## 4. Endpoint Definitions

Operations that create a new resource (a rights holder, a work, a license, a negotiation round, a contract, a signature, a royalty statement, an infringement case, or an external event injection) return `201 Created`. Operations that modify or transition an existing resource — patches, submits, terminates, signs (in the sense of advancing the contract via the signature endpoint), verifications, responses, escalations, resolutions, and dismissals — return `200 OK`. Operations on the test-driving and event-emission surfaces return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rights-holders` | Create a rights holder | `PlatformAdmin`, `RightsHolder` |
| GET | `/rights-holders/{holderId}` | Get a rights holder | `PlatformAdmin`, `RightsHolder` |
| POST | `/works` | Create a Work in `DRAFT` | `RightsHolder` |
| GET | `/works/{workId}` | Get Work | `PlatformAdmin`, `RightsHolder` |
| PATCH | `/works/{workId}` | Patch Work fields (`DRAFT` only) | `RightsHolder` |
| POST | `/works/{workId}/submit` | Submit Work for registration (`DRAFT` → `UNDER_REVIEW`) | `RightsHolder` |
| GET | `/works/{workId}/rights-chain` | Get rights-chain history for a Work (public) | `PlatformAdmin`, `RightsHolder` |
| POST | `/licenses` | Create a License in `OFFERED` | `RightsHolder` |
| GET | `/licenses/{licenseId}` | Get License | `PlatformAdmin`, `RightsHolder` |
| GET | `/licenses/{licenseId}/rounds` | List negotiation rounds in chronological order | `PlatformAdmin`, `RightsHolder` |
| POST | `/licenses/{licenseId}/rounds` | Submit a counter, accept, or withdraw on a License | `RightsHolder` |
| POST | `/licenses/{licenseId}/terminate` | Manually terminate an `EFFECTIVE` License | `RightsHolder` |
| POST | `/contracts` | Create a primary or supplementary Contract from an `ACCEPTED` License | `RightsHolder` |
| GET | `/contracts/{contractId}` | Get Contract | `PlatformAdmin`, `RightsHolder` |
| POST | `/contracts/{contractId}/signatures` | Submit a signature for the next required signer | `RightsHolder` |
| POST | `/licenses/{licenseId}/royalty-statements` | Create a RoyaltyStatement (provisional, final, or reversal entry) | `RightsHolder` |
| GET | `/licenses/{licenseId}/royalty-statements/{statementId}` | Get RoyaltyStatement | `PlatformAdmin`, `RightsHolder` |
| GET | `/licenses/{licenseId}/royalty-statements` | List RoyaltyStatements for a License | `PlatformAdmin`, `RightsHolder` |
| POST | `/infringement-cases` | Report an infringement case | `RightsHolder` |
| GET | `/infringement-cases/{caseId}` | Get InfringementCase | `PlatformAdmin`, `RightsHolder` |
| POST | `/infringement-cases/{caseId}/verify-ownership` | Verify ownership (`REPORTED` → `OWNERSHIP_VERIFIED`) | `PlatformAdmin` |
| POST | `/infringement-cases/{caseId}/respond` | Submit alleged-infringer response (`OWNERSHIP_VERIFIED` → `RESPONSE_RECEIVED`) | `RightsHolder` |
| POST | `/infringement-cases/{caseId}/escalate` | Escalate and issue takedown (`RESPONSE_RECEIVED` → `UNDER_ARBITRATION`) | `RightsHolder` |
| POST | `/infringement-cases/{caseId}/resolve` | Resolve with compensation (`UNDER_ARBITRATION` → `RESOLVED`) | `RightsHolder` |
| POST | `/infringement-cases/{caseId}/dismiss` | Dismiss case (`REPORTED` → `DISMISSED` or `UNDER_ARBITRATION` → `DISMISSED`) | `RightsHolder` |
| GET | `/audit-logs` | List audit logs with filters | `PlatformAdmin` |
| POST | `/_events/emit` | Inject an external event (`PAYMENT`, `E_SIGN`, `COPYRIGHT_AUTHORITY`, `DISTRIBUTION_PLATFORM`) | `PlatformAdmin` |
| POST | `/_clock/advance` | Advance the system clock (test-only) | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VERSION_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OWNERSHIP_SHARES_INVALID` | 422 Unprocessable Entity |
| `ERR_OWNERSHIP_PROOF_MISSING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CO_OWNER` | 409 Conflict |
| `ERR_WORK_NOT_REGISTERED` | 409 Conflict |
| `ERR_NOT_YOUR_TURN` | 409 Conflict |
| `ERR_EXCLUSIVE_LICENSE_VIOLATION` | 409 Conflict |
| `ERR_TERRITORY_TERM_OVERLAP` | 409 Conflict |
| `ERR_LICENSE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LICENSE_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_SIGNATURE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_DUPLICATE_SIGNATURE` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVALID_REVERSAL` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_PINNED_VERSION_STALE` | 409 Conflict |
| `ERR_PINNED_CERTIFICATE_STALE` | 409 Conflict |
| `ERR_DUPLICATE_EXTERNAL_EVENT` | 409 Conflict |
| `ERR_EVIDENCE_MISSING` | 422 Unprocessable Entity |
| `ERR_COMPENSATION_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_TERM` | 422 Unprocessable Entity |
| `ERR_HAS_PENDING_SETTLEMENTS` | 409 Conflict |
