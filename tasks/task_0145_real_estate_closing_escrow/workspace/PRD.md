# Real Estate Closing & Escrow API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Real Estate Closing & Third-Party Escrow API. The system orchestrates the entire closing workflow of a residential real estate transaction conducted through a neutral escrow agent: receiving an earnest money deposit from a buyer, ordering a title search and binding owner's and lender's title insurance, recording the buyer's acknowledgment of covenant, condition and restriction documents, issuing a Closing Disclosure that must age three business days before funding can occur, verifying every wire-disbursement instruction through an out-of-band callback to defeat wire fraud, settling all parties through the escrow pool, and — when the buyer or seller has elected one — interlocking the closing with an Internal Revenue Code §1031 like-kind exchange whose realized gain must be partitioned exactly into a taxable boot component and a deferred component.

The audience for this API is split across operational, fiduciary, and party-facing concerns. Escrow officers drive the file from open to close and bear primary fiduciary responsibility; title officers operate the title pipeline independently; a separate disbursement-approval operator exists strictly so that the same person who issued the most recent Closing Disclosure can never also confirm a wire or approve a disbursement (the segregation-of-duties control that the wire-fraud literature treats as the single most effective countermeasure against business email compromise); and the buyer and seller parties read the file and, in the buyer's case, sign the regulatory acknowledgments. The system is therefore as much a compliance audit log — every state transition is recorded as an `AuditEvent` — as it is a workflow engine, and it must be testable end-to-end against a logical clock so that the federally-mandated waiting periods (three business days for the Closing Disclosure, forty-five and one hundred eighty days for the §1031 exchange) can be exercised without waiting in wall time.

## 2. Global Specifications & System-Wide Principles

This section captures the cross-cutting rules that apply to every endpoint, regardless of the entity it touches.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the calling actor, and `X-User-Role`, which declares the capacity in which the actor is acting. A request that omits either header, or that names a role outside the closed set defined below, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not authorized for the targeted operation (per the role-to-endpoint matrix implicit in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles:

- `EscrowOfficer` — the neutral third-party escrow agent who opens the file, advances its status, issues and revises Closing Disclosures, drafts and submits wire instructions, proposes disbursements, settles funds, and closes or cancels the file. When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `confirmed_by_user_id` on `WireInstruction` or `approved_by_user_id` on `Disbursement` when a transition writes it, and as `actor_user_id` on every `AuditEvent`) but does not compare it to any entity's `id`.
- `TitleOfficer` — the third-party title underwriter who submits findings on a `TitleSearch`, clears or marks it defective, and quotes, binds, or voids `TitleInsurancePolicy` rows. When `X-User-Role` is `TitleOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; like the escrow officer, it is captured into audit trails but never compared to a stored entity `id`.
- `DisbursementApprover` — the operator who approves and sends a proposed disbursement, deliberately segregated from the escrow officer so that no single human can both issue a Closing Disclosure and release funds on the same escrow file. When `X-User-Role` is `DisbursementApprover`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; its only purpose vis-à-vis entity comparison is the segregation-of-duties check against whichever operator most recently issued the Closing Disclosure on the same escrow file.
- `Buyer` — a party in the transaction. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Party`; ownership checks on any resource that references a `Party` compare the resource's foreign-key field to `X-User-ID`. Concretely, a buyer can only acknowledge a Closing Disclosure or sign a CC&R disclosure on an escrow file whose `buyer_party_id` equals the caller's `X-User-ID`.
- `Seller` — the seller party. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Party`; ownership checks compare the resource's foreign-key field (typically `seller_party_id` on the related `EscrowFile`) to `X-User-ID`. Sellers have read-only access to their own escrow file and the artifacts within it and cannot mutate any state.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of records returned and defaults to 10 when omitted, with an enforced minimum of 1 and an enforced maximum of 100. The `offset` parameter expresses how many records to skip from the head of the result set and defaults to 0 when omitted. Lists are always sorted by the resource's `created_at` timestamp in ascending order unless an endpoint description explicitly states otherwise. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more` so a client can paginate without inspecting the data array.

### 2.4. Common Resource Properties and Server-Managed Fields

Every primary resource carries a server-generated `id` that is a UUID with no entity-type prefix. Most resources additionally carry a `created_at` ISO 8601 UTC timestamp with three fractional digits, an `updated_at` timestamp of identical format that is refreshed on every successful mutation, and an integer `version` that begins at 1 on creation and increments by exactly one on every successful mutation — including state transitions, cascaded mutations driven by another entity's transition, and any system sweep that rewrites the row.

Two entity classes are exceptions because they are immutable by design:

- A `CCRDisclosure` is a signed record. It carries only `id` and `created_at`; it has neither `updated_at` nor `version` because the buyer's acknowledgment is captured once and never edited.
- An `AuditEvent` is an append-only log entry. It carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

### 2.5. Hierarchical Consistency and Cascade Semantics

Although every artifact in this system references an `EscrowFile` directly by foreign key (the topology is flat, with no nested URLs), the closing workflow inherently couples the parent file to its dependents through cascade rules. When the escrow file is cancelled, the system cascades by the supplied `cancel_reason`: any `EarnestMoneyDeposit` that is still in `HELD` is disposed per the disposition rules in §3, every `TitleSearch` still in `ORDERED` is archived rather than completed, and every `TitleInsurancePolicy` still in `QUOTED` is voided. When a `TitleSearch` is marked defective, every `TitleInsurancePolicy` on the same `escrow_file_id` that is currently `QUOTED` is voided. When a `WireInstruction` is flagged as fraud, every `Disbursement` against that wire that sits in `PROPOSED` or `APPROVED` cascades to `REVERSED`. When a Closing Disclosure is revised, the prior `buyer_acknowledged_at` is cleared so the buyer must re-acknowledge after re-issuance. When an escrow file closes, any `EarnestMoneyDeposit` still in `HELD` is automatically transitioned to `RELEASED_TO_SELLER`. Every cascade-driven mutation refreshes the affected row's `updated_at` and increments its `version`, and every cascade produces an `AuditEvent`.

### 2.6. Optimistic Concurrency Control

Any endpoint that mutates a resource by its `id` accepts an optional `version` field in the request body. When present, it must equal the row's current `version`; otherwise the request is rejected with `ERR_VERSION_MISMATCH`. When the field is omitted, the server processes the mutation without an OCC check. This rule applies uniformly to all PATCH endpoints and all state-transition endpoints. The same error code is the loser-side result when two concurrent revisions of an `ISSUED` Closing Disclosure race: the first writer wins on the `ClosingDisclosure.version` row, and the second writer's request is rejected with `ERR_VERSION_MISMATCH`; whether the survivor's `triggering_change_kind` restarts or preserves the cooling-off clock is determined by §3.

### 2.7. Idempotency

Every POST endpoint and every state-transition endpoint requires the client to supply an `Idempotency-Key` HTTP header. If the same key is replayed with an identical request body, the server returns the original response. If the same key is replayed with a different request body, the server rejects the replay with `ERR_IDEMPOTENCY_REPLAY_MISMATCH`.

### 2.8. Validation Priority Ordering

Several validation families guard the same endpoint. They are evaluated in a fixed order so that a request which fails multiple checks always receives the highest-priority failure code. The order, from first to last, is: authentication (`ERR_UNAUTHENTICATED`); role authorization for the targeted endpoint (`ERR_FORBIDDEN_ROLE`); existence of every entity referenced by a path parameter or body foreign key, evaluated left-to-right against the URL (`ERR_NOT_FOUND`); foreign-key kind agreement for wire instructions (`ERR_BENEFICIARY_KIND_MISMATCH`); the entity's current state matching the from-state required by the requested transition (`ERR_INVALID_STATE`); any cross-entity state preconditions such as the parent escrow file's status or the §1031 disbursement having settled (`ERR_CROSS_ENTITY_STATE`); the segregation-of-duties check on wire confirmation and disbursement approval (`ERR_SOD_VIOLATION`); the out-of-band callback channel and completion flag on wire confirmation (`ERR_WIRE_CALLBACK_MISSING`); the Closing Disclosure three-business-day cooling-off (`ERR_CD_WAITING_PERIOD`); the §1031 forty-five-day identification deadline (`ERR_1031_45DAY_LAPSED`); the §1031 one-hundred-eighty-day exchange deadline (`ERR_1031_180DAY_LAPSED`); the lender-policy-requires-owner-policy referential check (`ERR_LENDERS_REQUIRES_OWNERS`); the title-cleared-before-bind referential check (`ERR_TITLE_NOT_CLEARED`); the earnest-money floor (`ERR_EMD_BELOW_FLOOR`); the mutual-release split invariant (`ERR_EMD_SPLIT_INVARIANT`); the §1031 gain invariant (`ERR_1031_GAIN_INVARIANT`); the CC&R-acknowledged-before-advance check (`ERR_CCR_NOT_ACKNOWLEDGED`); the escrow-pool overdraw check (`ERR_DISBURSEMENT_OVERDRAW`); the idempotency replay-mismatch check (`ERR_IDEMPOTENCY_REPLAY_MISMATCH`); and finally optimistic concurrency (`ERR_VERSION_MISMATCH`). For any malformed payload that is not covered by a more specific code — a missing required field, a value of the wrong JSON type, a numeric out-of-range — the response is `ERR_BAD_REQUEST` with HTTP 400.

### 2.9. Monetary Precision and Rounding

All monetary values — earnest money amounts, insurance premiums, the Closing Disclosure cash-to-close, the pro-rated tax and HOA credits, the §1031 gain components, and disbursement amounts — are computed in decimal arithmetic and stored to exactly two decimal places using round-half-up. The lone exception is the `EarnestMoneyDeposit` mutual-release split, which is exact at the cent level: the buyer's share and the seller's share must sum to the deposit amount exactly, with no rounding tolerance. Currency throughout the system is United States dollars.

### 2.10. The Business-Day Clock and Test-Driven Time

Several rules in this system are anchored to a logical clock rather than to elapsed wall time, so that a test suite can drive every waiting period without delay. The current server time is exposed through a read-only clock-now capability, and a privileged clock-advance capability moves the logical clock forward to a supplied ISO 8601 UTC instant `to`. Advancing the clock past the §1031 identification deadline or exchange deadline of an active `Exchange1031` triggers a system-actor sweep that fails the exchange to taxable.

The Closing Disclosure cooling-off period is three business days, where a business day is any day from Monday through Saturday — Saturdays count per CFPB Regulation Z §1026.19(f) — minus the eleven US federal holidays: New Year's Day on January 1, Martin Luther King Jr. Day on the third Monday of January, Washington's Birthday on the third Monday of February, Memorial Day on the last Monday of May, Juneteenth on June 19, Independence Day on July 4, Labor Day on the first Monday of September, Columbus Day on the second Monday of October, Veterans Day on November 11, Thanksgiving on the fourth Thursday of November, and Christmas Day on December 25. A holiday that falls on a Sunday is observed on the following Monday; otherwise the holiday is observed on its calendar date. Counting starts on the day after the Closing Disclosure's `issued_at`: the system walks forward day by day, counts a day only if it is a business day under the rule above, and stops at the moment the count reaches three; that moment, at 00:00 UTC of the third counted business day, is recorded as `earliest_funding_at`. The promotion of an acknowledged Closing Disclosure to ready-to-fund requires that `server_now` be greater than or equal to `earliest_funding_at`; otherwise the request is rejected with `ERR_CD_WAITING_PERIOD`. The §1031 forty-five-day identification rule and one-hundred-eighty-day exchange rule are evaluated by the same `server_now` comparison; the deadlines themselves are derived once when the exchange is created, by adding 45 and 180 calendar days respectively to the relinquished sale's `closing_date_planned`.

### 2.11. Wire Fraud Defense and Segregation of Duties

Two independent controls defend against wire fraud. The first is an out-of-band callback: a `WireInstruction` cannot advance from `PENDING_CONFIRMATION` to `CONFIRMED` unless the request body declares `callback_completed` as `true` and supplies a `callback_channel` from the closed set `VOICE_VERIFIED` or `IN_PERSON_VERIFIED` — any other value, or a missing or false `callback_completed`, yields `ERR_WIRE_CALLBACK_MISSING`. The second is segregation of duties: the actor confirming a `WireInstruction` callback, and the actor approving a `Disbursement`, must each have an `X-User-ID` different from the operator who triggered the most recent `ISSUED` transition on the Closing Disclosure for the same `escrow_file_id`. A violation is rejected with `ERR_SOD_VIOLATION` at HTTP 403. This is an authorization check rather than a serialization race: even if the violating request arrives strictly before a compliant peer's, it still fails on the actor-identity comparison.

### 2.12. Nested-Reference Resolution

When a request body or URL carries multiple identifiers — for instance, a `Disbursement` proposal that supplies both `escrow_file_id` and `wire_instruction_id`, or a `WireInstruction` creation that supplies both `escrow_file_id` and `beneficiary_party_id` — the server resolves them left to right as they appear in the URL and then in the body. The first unresolved identifier produces `ERR_NOT_FOUND` immediately, before any later identifier in the same request is dereferenced; the foreign-key kind-agreement check (which can produce `ERR_BENEFICIARY_KIND_MISMATCH`) runs only after every referenced entity has been resolved.

### 2.13. Conserved Financial Invariants

Two conserved-quantity invariants run through the system and are tested on every read of the affected resource. First, for any `EarnestMoneyDeposit` that has left `PENDING_FUNDS` or `HELD`, the sum of `forfeited_amount` and `refunded_amount` always equals the row's `amount` — the cents that entered the deposit are accounted for in exactly one of those two buckets, with no leakage. Second, for any `Exchange1031`, the sum of `recognized_gain` and `deferred_gain` always equals `realized_gain`. The §1031 invariant is re-checked at close-deferred time and on every GET of the row; a violation yields `ERR_1031_GAIN_INVARIANT` at HTTP 422.

### 2.14. Audit Trail

Every state transition and every mutation that the system performs — whether driven by a client request or by a cascade — appends one immutable `AuditEvent` keyed by the affected `escrow_file_id`. The event records the entity class on `subject_kind` (taking one of the values `EMD`, `TITLE_SEARCH`, `TITLE_POLICY`, `CCR`, `CD`, `WIRE`, `DISBURSEMENT`, or `EXCHANGE_1031`), the affected row's identifier on `subject_id`, the calling `X-User-ID` on `actor_user_id` and `X-User-Role` on `actor_role`, the transition or mutation name on `action`, and a SHA-256 hex of the canonical request body on `payload_hash` for tamper-evidence. Audit events are read-only and ordered by `created_at` ascending.

## 3. Business Logic & Workflows

### 3.1. Party and Property Registration

Before an escrow file can be opened, the operator first registers the participants. An `EscrowOfficer` creates each `Party` by supplying the legal `full_name` as it appears on the purchase contract, a `party_kind` drawn from the closed set `BUYER`, `SELLER`, `LENDER`, or `QUALIFIED_INTERMEDIARY`, and a `contact_email` used for the out-of-band wire-confirmation callbacks described later. Properties are likewise pre-registered with a `street_address`, a county-assessor `parcel_id`, the annual HOA dues on `hoa_annual_dues` (defaulting to zero when the parcel has no association), and the annual property tax on `tax_annual` (also defaulting to zero); the latter two are not merely descriptive — they are the proration inputs the system later consumes when it computes the Closing Disclosure's seller credits.

### 3.2. Opening an Escrow File and Receiving the Earnest Money

The escrow officer opens a file by referencing a previously-registered `property_id`, the `buyer_party_id`, the `seller_party_id`, optionally a `lender_party_id` (omitted on cash deals), optionally a `qi_party_id` (set only when the buyer or seller has elected a §1031 exchange), the agreed `purchase_price`, an optional `loan_amount` that defaults to zero, the `closing_date_planned` instant, and the optional boolean `is_1031_exchange` that defaults to false. The file's `status` begins at `OPEN`.

Once the file exists, the officer creates an `EarnestMoneyDeposit` by supplying the `escrow_file_id` and the `amount` in US dollars. The deposit begins in `PENDING_FUNDS`. Funding moves it to `HELD`, but only if the deposit honors the **earnest-money floor**: the `amount` must be greater than or equal to one percent of the parent escrow file's `purchase_price`, with exactly one percent permitted (the comparison is strictly inclusive — the boundary value passes). A deposit that falls beneath this threshold is rejected with `ERR_EMD_BELOW_FLOOR`. The floor check is enforced not only at funding time but at every endpoint that creates, modifies, or funds the deposit. Two operators racing to fund the same row serialize on `EarnestMoneyDeposit.status` — exactly one transition from `PENDING_FUNDS` to `HELD` succeeds, and the loser receives `ERR_INVALID_STATE` because the row has already advanced.

A `HELD` deposit later disposes along one of three branches depending on how the escrow concludes. When the file closes successfully, any deposit still `HELD` automatically transitions to `RELEASED_TO_SELLER` and its `forfeited_amount` is written to the deposit's full `amount` while `refunded_amount` stays at zero. When the file cancels under buyer default — typically a financing waiver the buyer controlled, or the buyer walking away after the inspection period — the same disposition fires: the entire deposit forfeits to the seller. When the file cancels because the seller failed to deliver clear title or violated the CC&R disclosure obligation, the deposit refunds to the buyer in full: `refunded_amount` becomes the deposit's `amount`, `forfeited_amount` stays at zero, and the status moves to `RELEASED_TO_BUYER`. The third branch is a mutual release: the parties agree to split the deposit, and the operator calls release with `reason` of `MUTUAL_RELEASE` and supplies `split_buyer_share` and `split_seller_share`. The two shares must sum to the deposit `amount` exactly — no rounding tolerance whatsoever — or the request is rejected with `ERR_EMD_SPLIT_INVARIANT`. On a successful mutual release, the status moves to `SPLIT`, `refunded_amount` is set to the buyer share and `forfeited_amount` is set to the seller share; the conserved-quantity invariant from §2 holds by construction.

### 3.3. Title Pipeline: Search, Defects, and Insurance Binding

A `TitleOfficer` orders a `TitleSearch` against the file by supplying the `escrow_file_id`; the search begins in `ORDERED`. The officer later submits findings — the boolean `chain_of_title_clean` indicating whether the recorded chain has any breaks, the dollar `open_liens_total` summing the unreleased balances on any liens against the parcel (defaulting to zero), and an integer `encumbrance_count` capturing recorded easements or encumbrances (also defaulting to zero) — which advances the search to `COMPLETED`. From `COMPLETED`, the search reaches `CLEARED` only when both `chain_of_title_clean` is true and `open_liens_total` is zero. The officer alternatively marks a completed search `DEFECTIVE`, which is a terminal state and which cascades any `TitleInsurancePolicy` on the same `escrow_file_id` still in `QUOTED` to `VOIDED`.

A `TitleInsurancePolicy` is created by quoting it against the escrow file. The officer supplies the `escrow_file_id`, the `policy_kind` from the closed set `OWNERS` or `LENDERS`, the dollar `insured_amount`, and an optional `simultaneous_issue` boolean that defaults to false. On creation the system freezes the policy's `premium` and stores the row in `QUOTED`. Binding a policy moves it to `BOUND` but only when (a) a `TitleSearch` on the same `escrow_file_id` is in `CLEARED` — otherwise the request is rejected with `ERR_TITLE_NOT_CLEARED` — and (b), if `policy_kind` is `LENDERS`, an `OWNERS` policy on the same `escrow_file_id` has already reached `BOUND`; absent such a peer the request is rejected with `ERR_LENDERS_REQUIRES_OWNERS`. A `QUOTED` policy can be voided directly or by cascade from a defective title search; a `BOUND` policy can also be voided, but only while the parent escrow file's `status` is in the set `OPEN`, `CONTINGENT_TITLE`, or `CONTINGENT_CD` — once the file has reached `CONTINGENT_WIRE` or beyond, the bound policy is locked.

The premium is computed from a three-tier rate schedule on `insured_amount` measured in thousands of dollars. The first one hundred thousand dollars is rated at five dollars per thousand; the band from one hundred thousand and one through five hundred thousand is rated at four dollars per thousand; every dollar above five hundred thousand is rated at three dollars per thousand. Concretely, the system computes the insured amount in thousands as an exact decimal, then takes the smaller of that quantity and one hundred as the first-tier thousands, takes the smaller of one hundred and the value of "the thousands less one hundred clamped to non-negative" — capped at four hundred — as the second-tier thousands (spanning the range above one hundred up to and including five hundred), and the value of "the thousands less five hundred clamped to non-negative" as the third-tier thousands. The base premium is the first-tier thousands multiplied by the five-dollar tier-one rate, plus the second-tier thousands multiplied by the four-dollar tier-two rate, plus the third-tier thousands multiplied by the three-dollar tier-three rate. For an `OWNERS` policy the final `premium` is the base rounded half-up to two decimal places, then taken as the larger of that figure and three hundred dollars (the owner's-policy floor). For a `LENDERS` policy without simultaneous issue the final `premium` is the base rounded half-up to two decimal places, then taken as the larger of that figure and two hundred dollars (the lender's-policy floor). For a `LENDERS` policy with `simultaneous_issue` set to true — which is honored only when a peer `OWNERS` policy on the same `escrow_file_id` is already `BOUND` at the moment the lender's policy is created — the system first multiplies the base by the simultaneous-issue discount factor of 0.40, rounds the product half-up to two decimal places, and then takes the larger of that and the two-hundred-dollar lender's-policy floor. The premium is frozen at quote time and does not change on bind.

### 3.4. CC&R Disclosure

Before the escrow file can advance past `CONTINGENT_TITLE` the buyer must acknowledge the property's covenants, conditions, and restrictions. The buyer creates a `CCRDisclosure` by supplying the `escrow_file_id`, a `ccr_document_hash` (a SHA-256 hex digest of the document delivered to the buyer for content integrity), and a `material_restrictions` array enumerating notable restriction codes such as `RENTAL_BAN`, `SHORT_TERM_RENTAL_BAN`, or `ARCHITECTURAL_REVIEW`. The server stamps `buyer_acknowledged_at` to the current server time when it accepts the record. The disclosure is immutable; the record itself carries no `updated_at` or `version`. If no `CCRDisclosure` exists for the `escrow_file_id` when the escrow officer attempts to advance the file past `CONTINGENT_TITLE`, the advance is rejected with `ERR_CCR_NOT_ACKNOWLEDGED`.

### 3.5. The Closing Disclosure and the 3-Business-Day Clock

A `ClosingDisclosure` is created by the escrow officer once the file has reached `CONTINGENT_CD`. The create payload supplies the `escrow_file_id`, `total_loan_costs` (the bundled loan-origination costs in US dollars, defaulting to zero), `seller_credits` (credits flowing from seller to buyer at closing, defaulting to zero), and `seller_days_owned` — the integer count of days from January 1 of the closing year through the planned closing date, inclusive, used to pro-rate seller-side annual obligations. On creation the row begins in `DRAFT`, the `version_number` starts at 1, and the system freezes `cash_to_close` along with the two pro-ration line items `prorated_tax_credit` and `prorated_hoa_credit`.

The cash-to-close formula is a deliberately pinned per-line-item-then-sum aggregation. First, the annual property tax from the parent property's `tax_annual` is multiplied by `seller_days_owned` and divided by the year basis of 365 days (leap years are ignored by design); the raw quotient is then rounded half-up to two decimal places and recorded as `prorated_tax_credit`. Independently, the annual HOA dues from the parent property's `hoa_annual_dues` are multiplied by `seller_days_owned` and divided by 365, with the raw quotient rounded half-up to two decimal places and recorded as `prorated_hoa_credit`. Per-line-item rounding precedes the sum: the system must not sum the raw quotients and then round, because the order of rounding and addition is observably different and the test suite pins the per-item-first order. Next, the system computes the earnest-money credit by summing the `amount` of every `EarnestMoneyDeposit` on the same `escrow_file_id` whose `status` is `HELD` at the moment of computation; deposits in `PENDING_FUNDS`, `RELEASED_TO_SELLER`, `RELEASED_TO_BUYER`, or `SPLIT` are excluded. Finally, `cash_to_close` is computed as the parent escrow file's `purchase_price`, minus the parent's `loan_amount`, minus the held-deposit total, minus `seller_credits`, minus `prorated_tax_credit`, minus `prorated_hoa_credit`, plus `total_loan_costs`. Each operand is already at two decimal places, so the final sum is exact at the cent level.

Issuance moves the disclosure from `DRAFT` to `ISSUED`. The system writes `issued_at` to the current server time and computes `earliest_funding_at` per the business-day clock described in §2: count starts on the day after `issued_at`, walks forward day by day, counts a day only when it is a business day (Monday through Saturday, minus the observed-holiday set), and records `earliest_funding_at` at 00:00 UTC on the third counted business day. Issuance is permitted only when the parent escrow file is in `CONTINGENT_CD`; a request issued against any other parent status is rejected with `ERR_CROSS_ENTITY_STATE`.

Once `ISSUED`, the buyer acknowledges receipt of the disclosure, which moves it to `ACKNOWLEDGED` and stamps `buyer_acknowledged_at` to the current server time. The acknowledge transition is restricted to a `Buyer` whose `X-User-ID` equals the parent escrow file's `buyer_party_id`. From `ACKNOWLEDGED` the disclosure can be promoted to `READY_TO_FUND`, but only when the server clock has reached or passed `earliest_funding_at`; a premature promotion is rejected with `ERR_CD_WAITING_PERIOD`.

Either the `ISSUED` or `ACKNOWLEDGED` disclosure can be revised. The escrow officer submits a `triggering_change_kind` from the closed set `NONE`, `APR_DELTA_OVER_THRESHOLD`, `LOAN_PRODUCT_CHANGE`, `PREPAYMENT_PENALTY_ADDED`, or `FEE_DELTA_UNDER_THRESHOLD`, along with optional updates to `total_loan_costs`, `seller_credits`, or `seller_days_owned`. The status moves to `REVISED`; if the prior status was `ACKNOWLEDGED`, `buyer_acknowledged_at` is cleared because the buyer must re-acknowledge the revised version. When the disclosure is subsequently re-issued out of `REVISED`, the system increments `version_number` by exactly one and re-freezes `cash_to_close`. Whether the cooling-off clock restarts depends entirely on the recorded `triggering_change_kind`: if the change is `APR_DELTA_OVER_THRESHOLD`, `LOAN_PRODUCT_CHANGE`, or `PREPAYMENT_PENALTY_ADDED`, the re-issue sets `issued_at` to the current server time and recomputes `earliest_funding_at` from scratch — the full three-business-day clock starts again. If the change is `FEE_DELTA_UNDER_THRESHOLD`, the re-issue still sets `issued_at` to the current server time, but `earliest_funding_at` is preserved unchanged from the prior version — the clock continues. From `DRAFT` the disclosure can be voided directly; the `ISSUED` status can also become `VOIDED` only as a cascade from the parent escrow file's cancellation. Two operators racing to revise the same `ISSUED` disclosure serialize on the row's `version`: exactly one revise succeeds and the loser receives `ERR_VERSION_MISMATCH`, with the survivor's `triggering_change_kind` determining the clock outcome.

### 3.6. Wire Instructions and the Out-of-Band Callback

For every disbursement the file will make, an escrow officer drafts a `WireInstruction` by supplying the `escrow_file_id`, the `beneficiary_kind` from the closed set `SELLER`, `LENDER_PAYOFF`, `QUALIFIED_INTERMEDIARY`, or `TAX_AUTHORITY`, the `beneficiary_party_id` referencing the `Party` who will receive the funds, the nine-digit ABA `routing_number`, and the `account_number_last4` (the last four digits of the destination account; the full number is stored outside the API surface). The wire is created in `DRAFT`. Submission moves it to `PENDING_CONFIRMATION`, at which point the system verifies that the `beneficiary_party_id` resolves to a `Party` whose `party_kind` matches the declared `beneficiary_kind`: `SELLER` beneficiaries must reference a seller party, `LENDER_PAYOFF` beneficiaries a lender party, `QUALIFIED_INTERMEDIARY` beneficiaries a qualified-intermediary party, and `TAX_AUTHORITY` beneficiaries either a party of the corresponding kind or a system-owned identifier. A mismatch is rejected with `ERR_BENEFICIARY_KIND_MISMATCH` at HTTP 422.

Confirmation is the wire-fraud chokepoint. The confirm-callback transition advances `PENDING_CONFIRMATION` to `CONFIRMED` only when the request body declares `callback_completed` as `true` and supplies a `callback_channel` from the closed set `VOICE_VERIFIED` or `IN_PERSON_VERIFIED` (any other value, or a missing or false `callback_completed`, yields `ERR_WIRE_CALLBACK_MISSING`), and only when the calling `X-User-ID` differs from whichever operator most recently triggered an `ISSUED` transition on a Closing Disclosure for the same `escrow_file_id` (a violation yields `ERR_SOD_VIOLATION`). On a successful confirmation the server stamps `confirmation_callback_at` to the current server time and writes `confirmed_by_user_id` to the calling actor. When two operators race to confirm the same wire and both pass the segregation check independently, exactly one transition to `CONFIRMED` succeeds and the loser is rejected with `ERR_INVALID_STATE` because the row is already `CONFIRMED`; when the same operator who issued the latest Closing Disclosure races with a peer, the violating actor's request is rejected with `ERR_SOD_VIOLATION` regardless of arrival order, because that is an authorization check and not a serialization race.

A `PENDING_CONFIRMATION` wire can also be flagged as fraud, moving it to the terminal `REJECTED_FRAUD_FLAG`; the flag cascades any `Disbursement` against that wire in `PROPOSED` or `APPROVED` to `REVERSED`. A `DRAFT` wire can be voided directly. A `CONFIRMED` wire can be voided only when no `Disbursement` against it has reached `SENT` or `SETTLED`; a request to void a wire that is locked by an active disbursement is rejected with `ERR_WIRE_LOCKED_BY_DISBURSEMENT`.

### 3.7. Disbursements and the Escrow Pool

Once a wire is `CONFIRMED`, the escrow officer proposes a `Disbursement` by supplying the `escrow_file_id`, the `wire_instruction_id`, and the dollar `amount`. The disbursement enters `PROPOSED`. A `DisbursementApprover` advances it to `APPROVED` only when (a) the referenced `WireInstruction.status` is `CONFIRMED`, (b) the parent escrow file is in `READY_TO_CLOSE` (or `CONTINGENT_WIRE` if this approval is the one that will advance the file past that contingency), and (c) the calling `X-User-ID` differs from whichever operator most recently triggered an `ISSUED` transition on the Closing Disclosure for the same escrow file. A segregation violation is rejected with `ERR_SOD_VIOLATION`. On approval the server writes `approved_by_user_id` to the calling actor. Two approvers racing on the same `PROPOSED` row serialize on `Disbursement.status`: exactly one transition to `APPROVED` succeeds and the loser receives `ERR_INVALID_STATE`.

An approved disbursement is sent by the approver, moving it to `SENT`, and is later settled by the escrow officer once the bank confirms posting, moving it to `SETTLED`. A disbursement can be reversed from `PROPOSED`, `APPROVED`, or `SENT` — either by an explicit reverse call or as a cascade from a wire being flagged fraudulent.

The escrow pool is the conserved-quantity invariant for funds. At any moment the sum of every `Disbursement.amount` whose `status` is `APPROVED`, `SENT`, or `SETTLED` on a given escrow file must not exceed the available pool, which is the sum of every `EarnestMoneyDeposit.amount` in `HELD` on that file, plus the parent's `loan_amount`, plus the buyer's `cash_to_close` from the file's latest issued Closing Disclosure. The residual — once the seller has been paid, the lender's payoff dispatched, the qualified intermediary funded if there is a §1031 exchange, and tax authorities paid — must be zero. Any proposal or approval that would breach the upper bound is rejected with `ERR_DISBURSEMENT_OVERDRAW`.

### 3.8. The §1031 Like-Kind Exchange

When the buyer or seller elects a like-kind exchange, the escrow officer initiates an `Exchange1031` tied to the same `escrow_file_id`, supplying the `relinquished_basis` (the adjusted basis of the property being given up), the `relinquished_sale_price`, an optional `cash_boot_received` of non-like-kind cash flowing to the exchanger (defaulting to zero), and an optional `mortgage_relief` capturing the excess of debt paid off on the relinquished side over debt assumed on the replacement (defaulting to zero). The exchange begins in `INITIATED`.

On creation the system freezes the gain calculation. The `realized_gain` is the `relinquished_sale_price` minus the `relinquished_basis`, rounded half-up to two decimal places. The boot total is the sum of `cash_boot_received` and `mortgage_relief`, rounded half-up to two decimal places. While the exchange is on a deferred path — that is, until it terminates at `CLOSED_DEFERRED` — the `recognized_gain` is the smaller of `realized_gain` and the boot total (this is the portion that becomes immediately taxable boot), and `deferred_gain` is `realized_gain` minus `recognized_gain` (carried into the replacement property's basis). The system also pins the two deadlines: `identification_deadline_at` is 45 calendar days after the relinquished sale's `closing_date_planned`, and `exchange_deadline_at` is 180 calendar days after the same instant.

The exchange advances to `IDENTIFIED` when the taxpayer identifies a replacement property, but only while `server_now` is less than or equal to `identification_deadline_at`; a request submitted after that moment is rejected with `ERR_1031_45DAY_LAPSED`. From `IDENTIFIED` the exchange reaches `CLOSED_DEFERRED` only when three conditions are met: `server_now` is less than or equal to `exchange_deadline_at` (otherwise `ERR_1031_180DAY_LAPSED`); a `Disbursement` to a `QUALIFIED_INTERMEDIARY` beneficiary on the same escrow file exists in `SETTLED` (otherwise `ERR_CROSS_ENTITY_STATE`); and the §1031 invariant — `recognized_gain` plus `deferred_gain` equals `realized_gain` — holds (otherwise `ERR_1031_GAIN_INVARIANT`).

A failed exchange reaches `FAILED_TAXABLE` either by an explicit fail request or by a system-actor sweep when the clock advances past one of the deadlines. On failure the system rewrites the gain components into the failed-exchange variant: `recognized_gain` becomes the full `realized_gain` (the entire gain is recognized) and `deferred_gain` is set to zero. The invariant continues to hold by construction. The `Exchange1031` row is also re-validated for the invariant on every GET; a read that finds the invariant violated returns `ERR_1031_GAIN_INVARIANT`.

### 3.9. The Escrow File Lifecycle and the Diamond of Contingencies

The escrow file traverses a diamond of contingencies. From the initial `OPEN` status, the system advances the file to `CONTINGENT_TITLE` once an `EarnestMoneyDeposit` for the file has reached `HELD`. From `CONTINGENT_TITLE` it advances to `CONTINGENT_CD` once three preconditions hold simultaneously: a `TitleSearch` on the file is in `CLEARED`, a `TitleInsurancePolicy` with `policy_kind` equal to `OWNERS` is in `BOUND`, and a `CCRDisclosure` exists for the file. From `CONTINGENT_CD` it advances to `CONTINGENT_WIRE` once a `ClosingDisclosure` for the file is in `READY_TO_FUND`. From `CONTINGENT_WIRE` it advances to `READY_TO_CLOSE` once every required `WireInstruction` — one per `beneficiary_kind` that has a non-zero disbursement — is in `CONFIRMED`. Advances are auto-evaluated when the escrow officer invokes the advance capability; preconditions are evaluated as a single batch, and the file can chain through multiple states in a single call when every check succeeds. Advancing past `CONTINGENT_TITLE` without a `CCRDisclosure` is rejected with `ERR_CCR_NOT_ACKNOWLEDGED`; advancing to `CONTINGENT_WIRE` while the Closing Disclosure has not yet matured beyond its three-business-day clock is rejected with `ERR_CD_WAITING_PERIOD`; any other cross-entity precondition failure is rejected with `ERR_CROSS_ENTITY_STATE`.

The escrow officer closes the file from `READY_TO_CLOSE` to `CLOSED` only when every `Disbursement` for the file has reached `SETTLED` and, if the file is a §1031 exchange, the linked `Exchange1031` has reached either `CLOSED_DEFERRED` or `FAILED_TAXABLE`. The close cascades any `EarnestMoneyDeposit` still in `HELD` to `RELEASED_TO_SELLER` and appends the corresponding audit events. The officer can also cancel the file from any non-terminal status — `OPEN`, `CONTINGENT_TITLE`, `CONTINGENT_CD`, or `CONTINGENT_WIRE` — by supplying a `cancel_reason` from the set `BUYER_DEFAULT`, `SELLER_DEFAULT`, `TITLE_DEFECT`, or `MUTUAL_RELEASE`; the reason chooses the earnest-money disposition variant described in §3.2. Once the file reaches `CLOSED` or `CANCELLED`, both states are terminal; a concurrent cancel against a file that is already closing serializes on `EscrowFile.status`, with exactly one terminal transition succeeding and the loser receiving `ERR_INVALID_STATE`.

### 3.10. List Filtering, the Audit Stream, and Test-Driving the Clock

Listing escrow files accepts three optional query filters — `status`, `buyer_party_id`, and `seller_party_id` — plus the standard `limit` and `offset` from §2.3. The audit-event listing endpoint is keyed by `escrow_file_id` and accepts only the pagination parameters, returning events sorted by `created_at` ascending. The clock-advance capability accepts a single body field `to` carrying an ISO 8601 UTC instant; the response payload exposes the new server time. A clock advance that crosses an `Exchange1031`'s `identification_deadline_at` or `exchange_deadline_at` triggers a system-actor sweep that fails the affected exchanges to `FAILED_TAXABLE`, rewriting `recognized_gain` to `realized_gain` and `deferred_gain` to zero, and appending an audit event for each such mutation.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources return `201 Created`. Operations that modify an existing resource — including all state transitions, releases, voids, reversals, cancellations, and closes — return `200 OK`. Every POST and state-transition endpoint requires an `Idempotency-Key` HTTP header; replay-with-mismatched-body is rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH`. All state-transition endpoints accept an optional `version` in the request body for optimistic concurrency.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/parties` | Create a Party (buyer, seller, lender, or qualified intermediary) | EscrowOfficer |
| GET    | `/parties/{partyId}` | Read a Party | EscrowOfficer, TitleOfficer, DisbursementApprover, Buyer, Seller |
| POST   | `/properties` | Create a Property | EscrowOfficer |
| GET    | `/properties/{propertyId}` | Read a Property | EscrowOfficer, TitleOfficer, Buyer, Seller |
| POST   | `/escrow-files` | Open an escrow file | EscrowOfficer |
| GET    | `/escrow-files/{escrowFileId}` | Read an escrow file | EscrowOfficer, TitleOfficer, DisbursementApprover, Buyer, Seller |
| GET    | `/escrow-files` | List escrow files (filter by status, buyer_party_id, seller_party_id; pagination) | EscrowOfficer, TitleOfficer, DisbursementApprover |
| POST   | `/escrow-files/{escrowFileId}/advance` | Evaluate next-state transitions and advance the escrow file | EscrowOfficer |
| POST   | `/escrow-files/{escrowFileId}/close` | Close the escrow file (READY_TO_CLOSE → CLOSED) | EscrowOfficer |
| POST   | `/escrow-files/{escrowFileId}/cancel` | Cancel the escrow file with a reason | EscrowOfficer |
| POST   | `/earnest-money` | Create an EMD record (status PENDING_FUNDS) | EscrowOfficer |
| GET    | `/earnest-money/{emdId}` | Read an EMD | EscrowOfficer, Buyer, Seller |
| POST   | `/earnest-money/{emdId}/fund` | Mark EMD funded (PENDING_FUNDS → HELD) | EscrowOfficer |
| POST   | `/earnest-money/{emdId}/release` | Release EMD per reason (HELD → RELEASED_TO_SELLER / RELEASED_TO_BUYER / SPLIT) | EscrowOfficer |
| POST   | `/title-searches` | Order a title search | EscrowOfficer, TitleOfficer |
| PATCH  | `/title-searches/{titleSearchId}` | Submit findings (ORDERED → COMPLETED) | TitleOfficer |
| POST   | `/title-searches/{titleSearchId}/clear` | Mark a completed title search CLEARED | TitleOfficer |
| POST   | `/title-searches/{titleSearchId}/mark-defective` | Mark a completed title search DEFECTIVE; cascades VOIDED to QUOTED policies | TitleOfficer |
| GET    | `/title-searches/{titleSearchId}` | Read a title search | EscrowOfficer, TitleOfficer, Buyer, Seller |
| POST   | `/title-policies` | Quote a title insurance policy (premium computed) | TitleOfficer |
| GET    | `/title-policies/{policyId}` | Read a title policy | EscrowOfficer, TitleOfficer, Buyer, Seller |
| POST   | `/title-policies/{policyId}/bind` | Bind a quoted policy | TitleOfficer |
| POST   | `/title-policies/{policyId}/void` | Void a quoted or bound policy | TitleOfficer |
| POST   | `/ccr-disclosures` | Record buyer acknowledgment of CC&R disclosure (immutable, append-only) | Buyer |
| GET    | `/ccr-disclosures/{ccrId}` | Read a CC&R disclosure record | EscrowOfficer, Buyer, Seller, TitleOfficer |
| POST   | `/closing-disclosures` | Create a CD draft for an escrow file (version 1) | EscrowOfficer |
| GET    | `/closing-disclosures/{cdId}` | Read a closing disclosure | EscrowOfficer, Buyer, Seller |
| POST   | `/closing-disclosures/{cdId}/issue` | Issue the CD (DRAFT → ISSUED, or REVISED → ISSUED at next version) | EscrowOfficer |
| POST   | `/closing-disclosures/{cdId}/acknowledge` | Buyer acknowledges receipt of the issued CD | Buyer |
| POST   | `/closing-disclosures/{cdId}/promote` | Promote ACKNOWLEDGED CD to READY_TO_FUND once cooling-off complete | EscrowOfficer |
| POST   | `/closing-disclosures/{cdId}/revise` | Revise an ISSUED or ACKNOWLEDGED CD; restart-or-preserve clock per reason | EscrowOfficer |
| POST   | `/closing-disclosures/{cdId}/void` | Void a CD draft or cascade target | EscrowOfficer |
| POST   | `/wire-instructions` | Create a wire instruction (DRAFT) | EscrowOfficer |
| GET    | `/wire-instructions/{wireId}` | Read a wire instruction | EscrowOfficer, DisbursementApprover |
| POST   | `/wire-instructions/{wireId}/submit` | Submit a DRAFT wire (DRAFT → PENDING_CONFIRMATION) | EscrowOfficer |
| POST   | `/wire-instructions/{wireId}/confirm-callback` | Confirm out-of-band callback (PENDING_CONFIRMATION → CONFIRMED); enforces SoD | EscrowOfficer, DisbursementApprover |
| POST   | `/wire-instructions/{wireId}/flag-fraud` | Flag a suspect wire (PENDING_CONFIRMATION → REJECTED_FRAUD_FLAG); cascades REVERSED to dependent disbursements | EscrowOfficer, DisbursementApprover |
| POST   | `/wire-instructions/{wireId}/void` | Void a wire (DRAFT, or CONFIRMED with no active disbursement) | EscrowOfficer |
| POST   | `/disbursements` | Propose a disbursement against a confirmed wire (PROPOSED) | EscrowOfficer |
| GET    | `/disbursements/{disbId}` | Read a disbursement | EscrowOfficer, DisbursementApprover |
| POST   | `/disbursements/{disbId}/approve` | Approve a proposed disbursement (PROPOSED → APPROVED); enforces SoD | DisbursementApprover |
| POST   | `/disbursements/{disbId}/send` | Send an approved disbursement (APPROVED → SENT) | DisbursementApprover |
| POST   | `/disbursements/{disbId}/settle` | Mark a sent disbursement settled (SENT → SETTLED) once bank confirms | EscrowOfficer |
| POST   | `/disbursements/{disbId}/reverse` | Reverse a disbursement from PROPOSED, APPROVED, or SENT | EscrowOfficer |
| POST   | `/exchanges` | Initiate a §1031 exchange tied to an escrow file | EscrowOfficer |
| GET    | `/exchanges/{exchangeId}` | Read an exchange | EscrowOfficer, Buyer, Seller |
| POST   | `/exchanges/{exchangeId}/identify` | Taxpayer identifies replacement property (INITIATED → IDENTIFIED); enforces 45-day rule | EscrowOfficer |
| POST   | `/exchanges/{exchangeId}/close-deferred` | Close as deferred (IDENTIFIED → CLOSED_DEFERRED); enforces 180-day rule and invariant | EscrowOfficer |
| POST   | `/exchanges/{exchangeId}/fail` | Mark exchange failed (recognized_gain := realized_gain; deferred_gain := 0) | EscrowOfficer |
| GET    | `/escrow-files/{escrowFileId}/audit-events` | List audit events for an escrow file (read-only; ordered by created_at asc) | EscrowOfficer, DisbursementApprover, TitleOfficer |
| POST   | `/_clock/advance` | Advance server clock to a specified ISO 8601 UTC instant (test-only) | EscrowOfficer |
| POST   | `/_clock/now` | Read current server clock | EscrowOfficer, TitleOfficer, DisbursementApprover, Buyer, Seller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_BENEFICIARY_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CROSS_ENTITY_STATE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_WIRE_CALLBACK_MISSING` | 422 Unprocessable Entity |
| `ERR_CD_WAITING_PERIOD` | 409 Conflict |
| `ERR_1031_45DAY_LAPSED` | 409 Conflict |
| `ERR_1031_180DAY_LAPSED` | 409 Conflict |
| `ERR_1031_GAIN_INVARIANT` | 422 Unprocessable Entity |
| `ERR_LENDERS_REQUIRES_OWNERS` | 409 Conflict |
| `ERR_TITLE_NOT_CLEARED` | 409 Conflict |
| `ERR_EMD_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_EMD_SPLIT_INVARIANT` | 422 Unprocessable Entity |
| `ERR_CCR_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_DISBURSEMENT_OVERDRAW` | 422 Unprocessable Entity |
| `ERR_IDEMPOTENCY_REPLAY_MISMATCH` | 409 Conflict |
| `ERR_VERSION_MISMATCH` | 409 Conflict |
| `ERR_WIRE_LOCKED_BY_DISBURSEMENT` | 409 Conflict |
| `ERR_BAD_REQUEST` | 400 Bad Request |
