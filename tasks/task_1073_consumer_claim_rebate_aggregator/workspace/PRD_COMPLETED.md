# Consumer Claim & Rebate Aggregator API — Product Requirements Document

## 1. Introduction

Consumers are entitled to money they rarely collect. Product rebates lapse, class-action settlements go unclaimed, warranty reimbursements are abandoned, and price-adjustment credits expire — not because the money is unavailable, but because discovering an entitlement, assembling the paperwork, filing before a deadline, and tracking the payout is more friction than most people will absorb. This platform is a **Consumer Claim & Rebate Aggregator**: it maintains a catalog of eligible settlements and rebate programs, matches consumers to the programs they likely qualify for, guides them through documentation and filing, and then shepherds each claim through review, approval, payout, and — where required — fraud adjudication.

The system is built around a finite pool of money. Every program funds its payouts from a fixed settlement fund, and once that fund is committed or exhausted the platform must reject or expire the claims that arrive too late. Two distribution philosophies coexist: **FIXED** programs settle each claim the moment a reviewer approves it, drawing the fund down claim by claim; **PRO_RATA** programs defer all settlement to the moment the program closes, then divide whatever fund remains proportionally across every approved claim. Layered over this are the platform's economics — a tiered contingency fee retained on each gross payout — and its defenses — an eligibility assessment, a two-tier fraud-risk score, and a segregation-of-duties rule that stops any single analyst from both raising and clearing the same fraud flag.

This document specifies the complete REST contract: the entities and their lifecycles, the calculations that determine every cent moved, the validation rules that guard each transition, and the role-based permissions that decide who may act. The reader implementing this API should treat §2 as the binding structural contract and §3 as the authoritative narrative of business behavior; the endpoint and error tables in §4 and §5 are indices back into that narrative, not substitutes for it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (with a single exception noted below) must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must name one of six recognized roles — `Anonymous`, `Consumer`, `ClaimReviewer`, `FraudAnalyst`, `ProgramManager`, or `PlatformAdmin`. If `X-User-Role` is missing or names an unrecognized role, or if `X-User-ID` is absent for any role other than `Anonymous`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, if the caller's role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles carry distinct identity semantics:

- When `X-User-Role` is `Anonymous`, the caller is an unauthenticated visitor whose identity is opaque and tied to no persisted entity; the only operation available is self-registration of a new consumer, and that single endpoint does not require `X-User-ID`.
- When `X-User-Role` is `Consumer`, the role is **entity-backed**: `X-User-ID` is the `id` of the acting `Consumer`. Ownership checks on any resource that references a consumer compare that resource's `consumer_id` to `X-User-ID` — a consumer filing, submitting, resubmitting, or uploading documents to a claim must be the claim's own `consumer_id`, and a consumer reading their claims, documents, matches, payouts, notifications, or eligibility assessments sees only their own. A consumer acting on a claim they do not own is rejected with `ERR_UNAUTHORIZED`.
- When `X-User-Role` is `ClaimReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition captures the acting reviewer — for example, as `assessed_by_user_id` on an `EligibilityAssessment` — but never compares it to any entity's `id`.
- When `X-User-Role` is `FraudAnalyst`, `X-User-ID` is likewise an opaque operator identifier. The server records it as `raised_by_user_id` when a flag is raised and as `cleared_by_user_id` when a flag is cleared, and it uses those two recorded values to enforce segregation of duties, but it never compares `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `ProgramManager`, `X-User-ID` is an opaque operator identifier used only for authentication; it is not tied to any persisted entity and is not compared to any resource's ownership field.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operational-superuser identifier. A `PlatformAdmin` may perform any operation in the system as an override of every other role's permissions, and the identifier is not compared to any entity's `id`.

Each endpoint in §4 lists the roles permitted to invoke it; `PlatformAdmin` is additionally permitted everywhere as the superuser override even where it is listed explicitly.

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

### 2.3. Pagination

Every list endpoint accepts two optional pagination parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100; a value outside that range is a malformed request. The `offset` parameter defaults to 0 and marks the number of leading records to skip. List endpoints always return their records sorted by `created_at` in ascending order (oldest first) before pagination is applied; records sharing an identical `created_at` (common because the logical clock is often held fixed) are broken by their creation sequence, i.e. the order in which they were inserted. The `meta` block of a list response reports the applied `limit` and `offset` alongside `total_count` (the total number of records matching the query before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix; clients never supply it. All timestamps — including `created_at`, `updated_at`, and the domain datetime fields — are ISO 8601 UTC values with three fractional digits.

Most entities are **fully versioned**: a `RebateProgram`, `Consumer`, `Match`, `Claim`, `ClaimDocument`, `Payout`, `FraudFlag`, and `EligibilityAssessment` each expose `created_at` (set once at creation), `updated_at` (refreshed on every mutation), and an integer `version` that starts at 1 and increments by 1 on each mutation that changes the resource. Two entities are deliberately **append-only ledger records** and carry only `id` and `created_at`: a `FundTransaction` and a `Notification` have neither an `updated_at` nor a `version`, because they are never mutated after they are written.

### 2.5. Monetary Precision and Rounding

All monetary quantities in the system are stored and computed as whole integer cents; the field names carry the `_cents` suffix as a reminder. Wherever a calculation produces a fractional cent — the tiered contingency fee and each pro-rata share are the only two places this arises — the result is rounded **half up** to the nearest whole cent, meaning a residue of exactly one half-cent rounds away from zero to the next higher cent. Aggregations that only add, subtract, or take a minimum of existing integer values are exact and require no rounding.

### 2.6. The Logical Clock and Temporal Evaluation

The platform does not read the host wall-clock. Instead it maintains a **logical clock** that every deadline, claim-window, and buffer evaluation consults for the current instant. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until an operator advances it; before any clock call is made, the clock returns this default rather than real time. A `PlatformAdmin` may move the clock to a supplied instant by providing a `to_iso8601` value; the operation echoes back the new `current_utc`. All references in this document to "the current instant" or "now" mean the logical clock's value at the moment the request is processed.

### 2.7. Optimistic Concurrency on the Shared Fund

FIXED programs draw down a shared, finite fund one approval at a time, and the platform protects that pool with optimistic concurrency control. Approving a claim requires the client to submit `expected_program_version` carrying the `version` of the target claim's `RebateProgram` as the client last observed it. Every FIXED approval that commits a payout advances the program's `version` (as does every payout reversal), so a reviewer who reads a program, then approves a claim while still holding the earlier program version, is working from a stale view of the remaining fund. When `expected_program_version` does not equal the program's current `version`, the approval is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), preventing the reviewer from committing an allocation against a fund balance they have not actually observed. No other endpoint takes a version field; only claim approval is version-guarded.

### 2.8. Fund Conservation and the Ledger Invariant

A program's `fund_remaining_cents` is never edited directly; it is always the derived consequence of the payouts committed against the program. Concretely, `fund_remaining_cents` equals `fund_total_cents` minus the sum of `gross_amount_cents` across every payout of that program whose status is `INITIATED`, `CLEARED`, or `FAILED`. Payouts in the `REVERSED` state are excluded from that sum, because a reversal credits their gross back to the fund. Every movement of fund money — a commitment at approval or settlement, and a credit at reversal — is recorded as an immutable `FundTransaction` capturing the `program_id`, the `related_claim_id` that caused it, a `type` of `DEBIT` or `CREDIT`, the absolute `amount_cents` moved, a `reason` of `PAYOUT_COMMIT` or `PAYOUT_REVERSAL`, and the `balance_after_cents` equal to the program's `fund_remaining_cents` immediately after the transaction. The program's own fund ledger is retrievable so that this running balance can be audited.

### 2.9. Segregation of Duties in Fraud Governance

Fraud adjudication follows a four-eyes principle. When a `FraudAnalyst` raises a flag, the platform records their `X-User-ID` as the flag's `raised_by_user_id`. When a flag is cleared, the platform records the clearing analyst's `X-User-ID` as `cleared_by_user_id`, and that value **must differ** from `raised_by_user_id`: no analyst may clear a flag they themselves raised. An attempt to clear one's own flag is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Confirming a flag carries no such restriction.

### 2.10. Cascading State Propagation

Several operations mutate more than one entity, and those secondary effects propagate transitively. Rejecting a supporting document can push its parent claim back into a revision loop; approving a FIXED claim can drain a fund to zero and thereby auto-reject every other still-open claim on the same program; closing a program can expire a whole cohort of in-flight claims; confirming a fraud flag can suspend a consumer. In every such cascade, each affected resource undergoes its own state transition, has its `updated_at` refreshed and its `version` incremented (for versioned entities), and emits whatever notifications its transition prescribes. The precise cascade chains are specified inline in §3 with the workflows that trigger them. Whenever a versioned entity is mutated — including as the downstream target of a cascade — its `version` increments by one and its `updated_at` advances to the logical-clock instant.

### 2.11. Validation Ordering and Error Precedence

When a single request could fail several checks, the platform evaluates them in a fixed precedence so that the returned error is deterministic. The order is: (1) authentication — a present, recognized role and, for non-`Anonymous` roles, a present `X-User-ID`, else `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted for the endpoint and, for a `Consumer`, owns the target resource, else `ERR_UNAUTHORIZED`; (3) existence — every id referenced in the path or body exists, validated left to right along the path, else `ERR_NOT_FOUND`; (4) request well-formedness — the body is well-formed, required fields are present, enums are valid, amounts that must be positive are positive, and interval fields satisfy `benefit_period_start` before `benefit_period_end` and `claim_window_open_at` before `claim_window_close_at`, else `ERR_INVALID_REQUEST`; (5) state — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE`; and only then (6) the business-rule checks specific to the operation. Within the business tier the applicable specific rules — segregation of duties, stale program version, cross-entity gates, temporal windows, document sufficiency, eligibility, fraud hold, risk threshold, and fund availability — are each described with their workflow in §3, where the relative order among them for a given operation is stated.

### 2.12. Nested Resource Access and Notifications

Sub-resources are addressed through their parent in the URL, and the platform validates each path segment left to right: a request for a claim's documents, payouts, fraud flags, or eligibility assessments first confirms the claim exists before evaluating the sub-collection, and a request for a program's report or fund ledger first confirms the program exists. All system-generated messages to consumers are `Notification` records delivered on the `channel` `EMAIL` — the only channel in this version — each carrying an `event_type`, a rendered `body`, a `read` flag that begins false, the `consumer_id` addressed, and the `related_claim_id` the message concerns where applicable. A consumer's notification inbox is retrievable and filterable by read state.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Programs and the Settlement Window

A `ProgramManager` (or a `PlatformAdmin`) seeds the catalog by creating a `RebateProgram`. Creation supplies the program's display `name`, a `settlement_case_id` that groups programs arising from the same underlying case or defendant, a `category` (one of `PRODUCT_REBATE`, `CLASS_ACTION`, `WARRANTY`, or `PRICE_ADJUSTMENT`), and a `distribution_method` of either `FIXED` or `PRO_RATA`. The money envelope is described by `fund_total_cents`, which must be greater than zero, an `advertised_amount_cents` headline figure of at least zero used for the provisional estimate, and a `per_claim_cap_cents` hard ceiling that must be greater than zero. Three optional eligibility knobs may accompany the creation: `eligibility_min_purchase_cents`, the minimum claimed spend a claim must assert to be eligible (defaulting to 0 when omitted); `requires_proof`, whether supporting documents are mandatory (defaulting to true); and `min_documents`, the minimum count of uploaded documents required to submit a claim (defaulting to 1). Finally, the claim window is fixed by `claim_window_open_at` (the inclusive instant claims may begin) and `claim_window_close_at` (the exclusive instant after which they may not be submitted). A newly created program begins in `DRAFT` with `status` set accordingly; its `fund_remaining_cents` is not yet meaningful until the program opens and is serialized as `null` while the program remains in `DRAFT`.

The `settlement_case_id` is not a foreign key — it is a grouping label — but it drives a scheduling guard. Before a new program is accepted, its claim window is checked against every existing program that shares the same `settlement_case_id`. These program windows are treated as **closed intervals** that must additionally be separated by a buffer of thirty days (the `PROGRAM_WINDOW_BUFFER_DAYS` constant). Formally, the new program conflicts with an existing sibling case-program unless the new window opens no earlier than the sibling's close instant plus thirty days, or the new window closes no later than the sibling's open instant minus thirty days. Because the intervals are closed, two windows that merely touch at an endpoint still conflict, and any gap shorter than the full thirty-day buffer conflicts as well. A conflicting window is rejected with `ERR_PROGRAM_WINDOW_CONFLICT`. (This guard applies only to program creation; it does not consider programs of a different `settlement_case_id`.)

Once satisfied with a draft, the `ProgramManager` **opens** the program, transitioning it from `DRAFT` to `OPEN`; opening a program that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Opening initializes `fund_remaining_cents` to the full `fund_total_cents`, arming the fund for draw-down. A program can later be **closed**, transitioning from `OPEN` to `CLOSED` (closing anything not `OPEN` is likewise an `ERR_INVALID_STATE`); the settlement and expiry consequences of closing are detailed in §3.8. Beyond `DRAFT`, `OPEN`, and `CLOSED`, a program may also reach `EXHAUSTED` automatically, as described in §3.5. `CLOSED` and `EXHAUSTED` are terminal. The catalog is browsable and a single program is directly retrievable; the browse endpoint filters by `category`, `status`, and `settlement_case_id`.

### 3.2. Consumers, Identity, and Program Discovery

Anyone may self-register as a `Consumer` without authentication by supplying an `email` (which must be unique across all consumers) and a `full_name`. Registration is the sole `Anonymous` operation; for this endpoint a request that omits the `X-User-Role` header entirely is treated as `Anonymous`. A newly registered consumer starts with `identity_status` of `UNVERIFIED`, a `total_recovered_cents` of 0, and both risk scores — `optimistic_risk_score` and `pessimistic_risk_score` — at 0. If the supplied `email` is already registered, the request is rejected with `ERR_DUPLICATE_EMAIL`. A `PlatformAdmin` may later **verify** a consumer, moving `identity_status` from `UNVERIFIED` to `VERIFIED`; verifying a consumer who is not `UNVERIFIED` is an `ERR_INVALID_STATE`, and verification recomputes the consumer's two risk scores. A consumer may also become `SUSPENDED` automatically, as described in §3.6; `SUSPENDED` is terminal.

To help consumers find money owed to them, a `ProgramManager` may create a `Match` between a consumer and a program by supplying the `consumer_id` and `program_id`. A match is born in `CANDIDATE` status and receives a computed `match_score` — a relevance figure on a 0-to-100 scale reflecting how actionable the program is at the instant the match is made. The score begins at 50; it gains 30 more points when the program's `status` is `OPEN`, and a further 20 points when the current instant falls within the program's claim window (at or after `claim_window_open_at` and strictly before `claim_window_close_at`); the total is capped at 100. A match becomes `CONVERTED` automatically when a claim is later filed referencing it (see §3.3); `CONVERTED` is terminal. Matches are individually retrievable and can be listed filtered by `consumer_id`, `program_id`, or `status`.

### 3.3. Filing a Claim: Drafts, Documents, and Submission

A `Consumer` files a claim by creating one against a program, supplying their own `consumer_id` (which must equal `X-User-ID`), the target `program_id`, the purchase or coverage interval as `benefit_period_start` (inclusive) and `benefit_period_end` (exclusive), and the `claimed_amount_cents` of eligible spend, which must be greater than zero. The claim is born in `DRAFT`. Optionally, the filer may include a `match_id` pointing at an existing `Match`; when present, that match is converted from `CANDIDATE` to `CONVERTED` as a side effect of the filing, but only if it belongs to the same `consumer_id` and `program_id` as the new claim — a match whose consumer or program disagrees with the claim is rejected with `ERR_MATCH_MISMATCH` (this mismatch check runs whenever `match_id` is supplied, regardless of the match's status). The conversion side effect fires only when the referenced match is still in `CANDIDATE` status; a match already `CONVERTED` (or otherwise non-`CANDIDATE`) that matches the claim's consumer and program is left unchanged and does not block the filing. At creation the claim's computed fields are still unset: `provisional_payout_cents`, `final_payout_cents`, `contingency_fee_cents`, and `net_payout_cents` have no value yet, `eligibility_status` is `UNASSESSED`, `needs_info_count` is 0, `submitted_at` is null, and `document_count` reflects however many documents have been attached so far.

Supporting evidence is attached by uploading a `ClaimDocument` to the claim. Each document specifies a `doc_type` (one of `RECEIPT`, `PROOF_OF_PURCHASE`, `ID`, or `OTHER`) and an opaque `file_ref` pointing at external storage; its `claim_id` is taken from the path, it enters in `PENDING` status with a null `rejection_reason`, and its arrival refreshes the parent claim's `document_count`, which tallies attached documents in any status. A consumer may upload documents only to their own claim. Documents are listable per claim, filterable by `status`.

**Submitting** a claim advances it from `DRAFT` to `SUBMITTED` and is the gate through which every filing must pass. A submit against a claim not in `DRAFT` is an `ERR_INVALID_STATE`. Beyond the state check, submission evaluates a fixed sequence of business rules in this order:

1. The program must be `OPEN`; submitting against a program in any other status is rejected with `ERR_PROGRAM_NOT_OPEN`.
2. The current instant must fall within the claim window — at or after the program's `claim_window_open_at` and strictly before its `claim_window_close_at`; a submission outside that half-open window is rejected with `ERR_CLAIM_WINDOW_CLOSED`.
3. The claim's benefit period must not overlap any other still-live claim of the same consumer on the same program. Overlap is judged on the **half-open** interval `[benefit_period_start, benefit_period_end)`: two periods overlap when the new period's start precedes the existing period's end **and** the existing period's start precedes the new period's end. Periods that merely touch — where one's end equals the other's start — do not overlap and are permitted. Only claims whose status is neither `REJECTED` nor `EXPIRED` count as live for this test; a collision yields `ERR_BENEFIT_PERIOD_OVERLAP`.
4. If the program `requires_proof`, the claim's `document_count` must be at least the program's `min_documents`; too few attached documents yields `ERR_INSUFFICIENT_DOCUMENTS`.
5. The claimed spend must clear the eligibility floor: `claimed_amount_cents` must be at least the program's `eligibility_min_purchase_cents`, else `ERR_NOT_ELIGIBLE`.

When all five pass, submission stamps `submitted_at` to the current instant, computes the forward-looking `provisional_payout_cents`, and sends the consumer a `Notification` with `event_type` `CLAIM_SUBMITTED`. The provisional estimate is deliberately optimistic: it is the smallest of the consumer's `claimed_amount_cents`, the program's headline `advertised_amount_cents`, and the program's `per_claim_cap_cents`. It ignores the fund entirely, because at submission time no fund competition has occurred; it is a headline figure the consumer sees while their claim waits in the queue.

### 3.4. Review, Eligibility, and the Revision Loop

A `ClaimReviewer` picks up a submitted claim by **starting review**, which moves it from `SUBMITTED` to `UNDER_REVIEW`; starting review on anything not `SUBMITTED` is an `ERR_INVALID_STATE`. Starting review produces an `EligibilityAssessment` recording the reviewer's `X-User-ID` as `assessed_by_user_id`, the current instant as `assessed_at`, its parent `claim_id`, and a determination broken into parts. The `min_purchase_met` flag is true when the claim's `claimed_amount_cents` is at least the program's `eligibility_min_purchase_cents`. The `documents_sufficient` flag is true when the program does not require proof, or else when the number of the claim's documents currently in `VERIFIED` status is at least the program's `min_documents` — note this counts only verified documents, a stricter test than the submit-time gate which counted attachments of any status. The overall `eligible` flag is true only when both `min_purchase_met` and `documents_sufficient` are true. The `reasons` array collects a reason code for each predicate that failed, in this fixed order: `MIN_PURCHASE_NOT_MET` when `min_purchase_met` is false, then `INSUFFICIENT_VERIFIED_DOCUMENTS` when `documents_sufficient` is false (the array is empty when the claim is eligible). Immediately after the assessment, the claim's `eligibility_status` is set to `ELIGIBLE` when the assessment's `eligible` is true and `INELIGIBLE` otherwise.

Review is a loop, not a one-shot. If the reviewer needs more from the consumer, **requesting info** moves the claim from `UNDER_REVIEW` to `NEEDS_INFO` (an optional `message` may accompany it), increments `needs_info_count` by one, and sends the consumer a `Notification` with `event_type` `NEEDS_INFO`; requesting info on a claim not `UNDER_REVIEW` is an `ERR_INVALID_STATE`. The consumer answers by **resubmitting**, which returns the claim from `NEEDS_INFO` to `UNDER_REVIEW` and re-runs the eligibility assessment logic to refresh `eligibility_status` against whatever documents and data now stand (recomputing the determination in place without persisting a new `EligibilityAssessment` record — only `start-review` creates an assessment); resubmitting a claim not in `NEEDS_INFO` is an `ERR_INVALID_STATE`. A claim can traverse this `NEEDS_INFO` ↔ `UNDER_REVIEW` cycle any number of times, and each request-info pass raises `needs_info_count`.

Document adjudication is woven into the same review phase. A `ClaimReviewer` **verifies** a document, moving it from `PENDING` to `VERIFIED` with no further effect, or **rejects** it, moving it from `PENDING` to `REJECTED`; either action on a document not `PENDING` is an `ERR_INVALID_STATE`. A rejection requires a `rejection_reason`, which is stored on the document, and it triggers a cascade: if the document's parent claim is currently in `SUBMITTED` or `UNDER_REVIEW`, that claim is pushed into `NEEDS_INFO`, its `needs_info_count` increments by one, and a `NEEDS_INFO` notification is dispatched to the consumer — the same revision loop, entered from the document side.

### 3.5. Approval, Payout Computation, and Fund Draw-Down

Approving a claim advances it from `UNDER_REVIEW` to `APPROVED` and is the most heavily guarded transition in the system. Approval is requested by a `ClaimReviewer` and must carry `expected_program_version`. The checks are evaluated in this precedence: first the claim must actually be `UNDER_REVIEW`, else `ERR_INVALID_STATE`; then the optimistic-concurrency check — `expected_program_version` must equal the program's current `version`, else `ERR_STALE_PROGRAM_VERSION` (HTTP 412); then eligibility — the claim's `eligibility_status` must be `ELIGIBLE`, else `ERR_NOT_ELIGIBLE`; then the fraud hold — the claim's `fraud_status` must not be `CONFIRMED`, else `ERR_FRAUD_HOLD`; then the risk gate — the consumer's `optimistic_risk_score` must be strictly below the risk threshold of 50, else `ERR_RISK_THRESHOLD_EXCEEDED`; and finally, for FIXED programs only, the fiscal gate — the computed `final_payout_cents` must come out greater than zero, which requires `fund_remaining_cents` to be greater than zero, else `ERR_FUND_EXHAUSTED`.

What happens on a successful approval depends on the program's `distribution_method`. For a **FIXED** program, approval settles the claim immediately in a single cascade. First the money is computed. The `final_payout_cents` is the smallest of the claim's `provisional_payout_cents`, the program's `per_claim_cap_cents`, and the program's live `fund_remaining_cents` — this last clamp is what makes the final figure diverge from the provisional estimate once the fund is partly depleted. The `contingency_fee_cents` retained by the platform on that gross is then computed in a fixed sequence of steps (detailed in §3.9). The `net_payout_cents` is the `final_payout_cents` minus the `contingency_fee_cents`, evaluated in that pinned order — gross first, then fee, then the subtraction. With the amounts fixed, the cascade continues: a `Payout` is created in `INITIATED` status whose `gross_amount_cents` equals the claim's `final_payout_cents`, whose `fee_amount_cents` equals the claim's `contingency_fee_cents`, whose `net_amount_cents` equals `gross_amount_cents` minus `fee_amount_cents`, and whose `attempt_count` begins at 1. The program's fund is then debited by the gross: a `FundTransaction` of `type` `DEBIT` and `reason` `PAYOUT_COMMIT` is written recording the `related_claim_id` and the `balance_after_cents`, and `fund_remaining_cents` is recomputed accordingly. The program's `version` increments by one — the very advance that the optimistic-concurrency check defends. Finally the consumer receives a `Notification` with `event_type` `CLAIM_APPROVED`.

The FIXED cascade has a terminal consequence. If debiting the fund brings `fund_remaining_cents` to exactly zero, the program automatically transitions from `OPEN` to `EXHAUSTED`. Exhaustion is itself a cascade: every other claim of that program still sitting in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is transitioned to `REJECTED`, and each such claim's consumer receives a `CLAIM_REJECTED` notification. This is how a finite pool closes itself off the instant the last cent is committed.

For a **PRO_RATA** program, approval is comparatively quiet: no payout is created and no money computed yet, because all settlement for pro-rata programs is deferred to program close (see §3.8). The claim simply reaches `APPROVED`, the program's `version` still increments by one, and the consumer still receives a `CLAIM_APPROVED` notification.

A reviewer may instead **reject** a claim, moving it from either `UNDER_REVIEW` or `NEEDS_INFO` to `REJECTED` (an optional `reason` may accompany it); rejecting from any other state is an `ERR_INVALID_STATE`. Rejection sends a `CLAIM_REJECTED` notification and recomputes the consumer's risk scores, since a rejected claim raises the consumer's risk. `APPROVED`, `REJECTED`, and `EXPIRED` are the terminal states of a claim.

### 3.6. Fraud Detection and Consumer Risk

A `FraudAnalyst` guards the platform against abuse by raising a `FraudFlag` on a claim, supplying a `reason` of `DUPLICATE`, `IDENTITY_MISMATCH`, `SUSPICIOUS_DOCS`, `INELIGIBLE_PURCHASE`, or `OTHER`. The flag is created in `OPEN` status with its `claim_id` from the path and its `raised_by_user_id` set to the analyst's `X-User-ID`. Raising a flag pushes the claim's derived `fraud_status` to `FLAGGED`, recomputes the consumer's risk scores, and notifies the consumer with a `FRAUD_FLAGGED` notification. A claim's `fraud_status` is always derived from its flags: it is `CONFIRMED` if any of the claim's flags is confirmed, otherwise `FLAGGED` if any flag remains open, otherwise `CLEAR`.

An analyst **confirms** a flag, moving it from `OPEN` to `CONFIRMED` (an optional `resolution_note` may be supplied); confirming a flag not `OPEN` is an `ERR_INVALID_STATE`. Confirmation recomputes the parent claim's `fraud_status` to `CONFIRMED`, suspends the consumer — moving `identity_status` to `SUSPENDED` from either `UNVERIFIED` or `VERIFIED` whenever any flag on any of the consumer's claims is confirmed — and recomputes the consumer's risk scores. Alternatively an analyst **clears** a flag, moving it from `OPEN` to `CLEARED` (again an optional `resolution_note`); clearing a non-`OPEN` flag is an `ERR_INVALID_STATE`. Clearing is subject to segregation of duties: the clearing analyst's `X-User-ID` must differ from the flag's `raised_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. On a successful clear the flag records `cleared_by_user_id` as the acting `X-User-ID`, the parent claim's `fraud_status` is recomputed (returning to `CLEAR` when no open or confirmed flags remain), and the consumer's risk scores are recomputed. `CONFIRMED` and `CLEARED` are terminal flag states. Fraud flags are listable per claim, filterable by `status`.

The consumer's two risk scores are the platform's safety dial, recomputed whenever a flag is raised, confirmed, or cleared, whenever a claim is rejected, and whenever a consumer is verified. Both begin from a weighted tally of signals: each confirmed fraud flag across the consumer's claims contributes 40 points, each rejected claim contributes 15 points, and the consumer being anything other than `VERIFIED` contributes a flat 20 points. The two scores differ in exactly one term. The `optimistic_risk_score` — the gate for claim approval — counts only those three signals and deliberately ignores flags that are merely open and unconfirmed. The `pessimistic_risk_score` — the gate for payout clearing — additionally adds 25 points for each open fraud flag across the consumer's claims. Each score is capped at 100. Because the pessimistic score includes open flags, it can cross the threshold of 50 while the optimistic score, for the same consumer, does not — a claim may therefore approve while its eventual payout is blocked from clearing until the open flags are resolved.

### 3.7. Settling, Failing, Retrying, and Reversing Payouts

Payouts are operated exclusively by a `PlatformAdmin`. A payout created at approval sits in `INITIATED` until it is cleared. **Clearing** a payout moves it from `INITIATED` to `CLEARED`, and its checks run in this order: the payout must be `INITIATED`, else `ERR_INVALID_STATE`; the recipient consumer's `identity_status` must be `VERIFIED`, else `ERR_CONSUMER_NOT_VERIFIED`; and the consumer's `pessimistic_risk_score` must be strictly below 50, else `ERR_RISK_THRESHOLD_EXCEEDED`. On a successful clear, the consumer's `total_recovered_cents` grows by the payout's `net_amount_cents`, and the consumer receives a `PAYOUT_CLEARED` notification. A consumer's `total_recovered_cents` is precisely the sum of `net_amount_cents` across all of that consumer's payouts currently in `CLEARED` status.

If a disbursement cannot be completed, the admin **fails** the payout, moving it from `INITIATED` to `FAILED` (an optional `reason` may be given) and sending a `PAYOUT_FAILED` notification. A failed payout can be **retried**, moving it back from `FAILED` to `INITIATED` and incrementing its `attempt_count` by one. A retry deliberately does **not** re-debit the fund — the fund commitment already happened at approval — so the money is not moved a second time; the payout simply re-enters the disbursement queue. Failing a non-`INITIATED` payout, or retrying a non-`FAILED` payout, is an `ERR_INVALID_STATE`. Note that because `fund_remaining_cents` counts payouts in `INITIATED`, `CLEARED`, and `FAILED` status alike, a payout moving among these three states never changes the program's remaining fund.

A cleared payout can be **reversed**, moving it from `CLEARED` to `REVERSED` (an optional `reason` may be given); reversing anything not `CLEARED` is an `ERR_INVALID_STATE`. Reversal is a compensating action that restores both invariants it originally disturbed. It credits the program's fund by the payout's `gross_amount_cents` — writing a `FundTransaction` of `type` `CREDIT` and `reason` `PAYOUT_REVERSAL` with the resulting `balance_after_cents`, recomputing `fund_remaining_cents` (which now excludes this `REVERSED` payout's gross), and incrementing the program's `version` by one. It also unwinds the recovery it recorded, subtracting the payout's `net_amount_cents` from the consumer's `total_recovered_cents`. `REVERSED` is the terminal state of a payout. Payouts are listable per claim, filterable by `status`.

### 3.8. Closing a Program: Pro-Rata Settlement and Expiry

Closing a program moves it from `OPEN` to `CLOSED` and is where PRO_RATA programs finally pay out. Closing something not `OPEN` is an `ERR_INVALID_STATE`. Two things happen at close, in order: the settlement, then the expiry sweep.

For a `PRO_RATA` program, the settlement runs a waterfall allocation over exactly the claims of that program whose status is `APPROVED`, processed in `created_at` ascending order (ties broken by `created_at`; the `id` is never used as a tiebreaker). Let the total demand be the sum of `claimed_amount_cents` across those approved claims, and let the pool be the program's `fund_total_cents`. If the total demand is no greater than the pool, the fund covers everyone: each claim's `final_payout_cents` is the smaller of its own `claimed_amount_cents` and the program's `per_claim_cap_cents`. If the total demand exceeds the pool, the pool is shared proportionally, with rounding order that is outcome-determining and therefore pinned. For each approved claim, first compute its raw share as its `claimed_amount_cents` divided by the total demand, multiplied by the pool. Then take the floor of each raw share down to a whole cent — flooring every claim **first**, before any remainder is handled. Sum those floored shares and subtract from the pool to get the leftover whole cents (the remainder). Distribute the remainder one cent at a time, giving a single extra cent to each claim in `created_at` ascending order in one pass, stopping as soon as the remainder is exhausted. Each claim's `final_payout_cents` is its floored share plus one cent if it received a remainder cent. The system never sums the shares and rounds once at the end.

Once each approved claim's `final_payout_cents` is fixed, the settlement finishes each claim in `created_at` ascending order exactly as a FIXED approval would: it computes the `contingency_fee_cents` (§3.9) and the `net_payout_cents` (gross minus fee), creates a `Payout` in `INITIATED` status carrying those `gross_amount_cents`, `fee_amount_cents`, and `net_amount_cents`, and debits the fund by that gross through a `FundTransaction` of `reason` `PAYOUT_COMMIT`, recomputing `fund_remaining_cents` as it goes.

After settlement (for a FIXED program there is no settlement step, only this sweep), closing expires the stragglers: every claim of the program still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` transitions to `EXPIRED`, and each such claim's consumer receives a `CLAIM_EXPIRED` notification. `EXPIRED` claims are terminal and never settle.

### 3.9. The Contingency Fee and Program Reporting

The platform retains a contingency fee on every gross payout, whether that payout arises from a FIXED approval or a PRO_RATA settlement. The fee is computed from the claim's gross — its `final_payout_cents` — in a fixed sequence of steps that must be applied in exactly this order. **First**, select the rate by tier, where the tier boundaries are inclusive at their lower edge and exclusive at their upper edge: a gross below 10,000 cents takes a rate of 15 percent; a gross of at least 10,000 cents but below 50,000 cents takes 20 percent (so a gross of exactly 10,000 cents lands in this middle tier); and a gross of 50,000 cents or more takes 25 percent. **Second**, compute the raw fee as the gross multiplied by that rate, rounded half up to a whole cent. **Third**, clamp the raw fee into an allowed band by raising it up to a floor of 500 cents if it fell below that floor and capping it at a ceiling of 25,000 cents if it rose above that ceiling; then, as a further cap, ensure the result never exceeds the gross itself. **Fourth and last**, apply the loyalty discount: if the recipient consumer's `identity_status` is `VERIFIED`, the clamped fee is reduced by ten percent — multiplied by the remaining ninety percent and rounded half up to a whole cent — otherwise the clamped value stands as the fee. The result is the claim's `contingency_fee_cents`. This ordering is load-bearing: the discount is applied after the clamp and gross-cap, never before.

Program performance is surfaced through a computed report available to a `ProgramManager` or `PlatformAdmin`, keyed by `program_id`. The report returns the `total_claims` filed against the program, and the breakdown of terminal outcomes as `approved_claims`, `rejected_claims`, and `expired_claims` (the counts of the program's claims in `APPROVED`, `REJECTED`, and `EXPIRED` status respectively). On the money side it reports `total_committed_cents` (the sum of `gross_amount_cents` across the program's payouts that have not been reversed), `total_fees_cents` (the sum of their `fee_amount_cents`), and `total_cleared_cents` (the sum of `net_amount_cents` across the program's payouts in `CLEARED` status). It echoes the program's `fund_total_cents` and current `fund_remaining_cents`, and it reports `average_net_payout_cents`, the mean `net_amount_cents` across the program's `CLEARED` payouts rounded half up to a whole cent, or zero when the program has no cleared payouts. The program's underlying fund ledger — the ordered list of every `FundTransaction` — is separately retrievable so that the committed and remaining figures can be reconciled transaction by transaction.

## 4. Endpoint Definitions

All endpoints are mounted under the `/rebate-aggregator` prefix. Creating a brand-new resource returns HTTP 201; all state-transition and modification operations, and all reads, return HTTP 200. Request and response bodies follow the envelope of §2.2; the request payload, computed side effects, and response contents for each operation are specified in the §3 narratives, not repeated here. Where `PlatformAdmin` is listed, it acts either in its own right or as the superuser override of the named role.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/rebate-aggregator/programs` | Create a rebate/settlement program (DRAFT); enforces the same-case window-conflict rule | ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/programs/{id}` | Get a single program | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/programs` | List/browse the catalog (filter by category, status, settlement_case_id) | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/programs/{id}/report` | Aggregated program statistics (computed read) | ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/programs/{id}/fund-transactions` | The program's fund ledger | ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/programs/{id}/open` | Open a program for claims (DRAFT → OPEN) | ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/programs/{id}/close` | Close a program (OPEN → CLOSED); pro-rata settle and expire stragglers | ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/consumers` | Register a consumer (self-service) | Anonymous, PlatformAdmin |
| GET | `/rebate-aggregator/consumers/{id}` | Get a consumer | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/consumers/{id}/verify` | Verify a consumer's identity (UNVERIFIED → VERIFIED) | PlatformAdmin |
| GET | `/rebate-aggregator/consumers/{id}/notifications` | List a consumer's notifications (filter by read) | Consumer, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/matches` | Create a candidate match between a consumer and a program | ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/matches/{id}` | Get a match | Consumer, ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/matches` | List matches (filter by consumer_id, program_id, status) | Consumer, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/claims` | Create a DRAFT claim; an optional match_id converts that match | Consumer, PlatformAdmin |
| GET | `/rebate-aggregator/claims/{id}` | Get a claim | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| GET | `/rebate-aggregator/claims` | List claims (filter by consumer_id, program_id, status) | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/documents` | Upload a supporting document (PENDING) | Consumer, PlatformAdmin |
| GET | `/rebate-aggregator/claims/{id}/documents` | List a claim's documents (filter by status) | Consumer, ClaimReviewer, FraudAnalyst, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/submit` | Submit a claim (DRAFT → SUBMITTED); runs window/overlap/docs/eligibility checks | Consumer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/start-review` | Begin review (SUBMITTED → UNDER_REVIEW); creates an eligibility assessment | ClaimReviewer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/request-info` | Request more info (UNDER_REVIEW → NEEDS_INFO) | ClaimReviewer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/resubmit` | Resupply info (NEEDS_INFO → UNDER_REVIEW) | Consumer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/approve` | Approve a claim (UNDER_REVIEW → APPROVED); OCC on program version; FIXED commits payout | ClaimReviewer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/reject` | Reject a claim (UNDER_REVIEW or NEEDS_INFO → REJECTED) | ClaimReviewer, PlatformAdmin |
| GET | `/rebate-aggregator/claims/{id}/eligibility-assessments` | List a claim's eligibility assessments | Consumer, ClaimReviewer, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/documents/{id}/verify` | Verify a document (PENDING → VERIFIED) | ClaimReviewer, PlatformAdmin |
| POST | `/rebate-aggregator/documents/{id}/reject` | Reject a document (PENDING → REJECTED); cascades parent claim to NEEDS_INFO | ClaimReviewer, PlatformAdmin |
| POST | `/rebate-aggregator/claims/{id}/fraud-flags` | Raise a fraud flag on a claim (OPEN) | FraudAnalyst, PlatformAdmin |
| GET | `/rebate-aggregator/claims/{id}/fraud-flags` | List a claim's fraud flags (filter by status) | FraudAnalyst, ClaimReviewer, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/fraud-flags/{id}/confirm` | Confirm a fraud flag (OPEN → CONFIRMED); suspends the consumer | FraudAnalyst, PlatformAdmin |
| POST | `/rebate-aggregator/fraud-flags/{id}/clear` | Clear a fraud flag (OPEN → CLEARED); segregation of duties enforced | FraudAnalyst, PlatformAdmin |
| GET | `/rebate-aggregator/claims/{id}/payouts` | List a claim's payouts (filter by status) | Consumer, ClaimReviewer, ProgramManager, PlatformAdmin |
| POST | `/rebate-aggregator/payouts/{id}/clear` | Clear a payout (INITIATED → CLEARED); requires verified consumer and risk gate | PlatformAdmin |
| POST | `/rebate-aggregator/payouts/{id}/fail` | Mark a payout failed (INITIATED → FAILED) | PlatformAdmin |
| POST | `/rebate-aggregator/payouts/{id}/retry` | Retry a failed payout (FAILED → INITIATED); does not re-debit the fund | PlatformAdmin |
| POST | `/rebate-aggregator/payouts/{id}/reverse` | Reverse a cleared payout (CLEARED → REVERSED); credits fund, unwinds recovery | PlatformAdmin |
| POST | `/rebate-aggregator/_clock/set_current_utc` | Set the server logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier and its HTTP status. The condition that triggers each error is specified in the §2 and §3 narratives, not repeated here.

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_MATCH_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_PROGRAM_NOT_OPEN` | 409 |
| `ERR_CONSUMER_NOT_VERIFIED` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 |
| `ERR_BENEFIT_PERIOD_OVERLAP` | 409 |
| `ERR_PROGRAM_WINDOW_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_DOCUMENTS` | 409 |
| `ERR_NOT_ELIGIBLE` | 409 |
| `ERR_FRAUD_HOLD` | 409 |
| `ERR_RISK_THRESHOLD_EXCEEDED` | 409 |
| `ERR_FUND_EXHAUSTED` | 409 |










