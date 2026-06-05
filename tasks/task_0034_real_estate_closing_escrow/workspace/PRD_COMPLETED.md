# Real Estate Closing & Escrow API — Product Requirements Document

## 1. Introduction

A real estate closing is the moment at which a written purchase agreement collapses into an enforceable transfer of title, a payoff of the seller's lender, a release of buyer funds, and (when 1031 routing is in play) an exchange-of-property tax deferral. The interval between contract signature and recording is short, the dollar amounts are large, and every participant — buyer, seller, lender, title company, qualified intermediary, escrow officer — is a different organisation with no shared system of record. Real-world closings fail when this interval is mismanaged: earnest money lands in the wrong account, a wire is sent to a fraudulent beneficiary because nobody called the title company back, a Closing Disclosure is acknowledged before its mandatory three-day waiting period has elapsed, or a 1031 exchange's 45-day identification window quietly expires while the parties are still negotiating.

This API is a third-party escrow platform that serializes every one of those moments. It is the single neutral system of record for a closing: it accepts the purchase agreement, opens an escrow account against it, records earnest money deposits, drives the title search and title insurance, captures the CC&R review, runs the Closing Disclosure through its three-day clock, locks every wire-instruction under a two-person voice-callback control, and at close time executes a deterministic disbursement waterfall across all queued payments. When the underlying transaction is a 1031 like-kind exchange, the same workflow re-routes the seller's proceeds to a qualified intermediary and tracks the 45-day and 180-day federal deadlines.

The product manager's view: every operation in this system is an audit-grade event. We trade implementation flexibility for procedural rigour — strict role separation, optimistic concurrency on the parent agreement and the underlying title search, and a refusal to ever proceed when one of the named compliance gates is open.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` carries the caller's identifier. `X-User-Role` declares the caller's role and must be one of three exact strings: `EscrowOfficer`, `TitleAgent`, or `ComplianceOfficer`. A request that omits `X-User-Role`, or that supplies a value not in this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a request that omits `X-User-ID` (or supplies it empty) is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but not permitted on the called endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

All three roles are entity-backed: each is registered as a row of the `User` resource (carrying the operator's legal name in `full_name`) whose `role` field carries the role name exactly as written above. When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` compare the resource's foreign-key field (for example, `escrow_officer_id` on `EscrowAccount`, or `callback_verifier_id` on `WireInstruction`) against `X-User-ID`. The same rule holds when `X-User-Role` is `TitleAgent` or `ComplianceOfficer`: `X-User-ID` is the `id` of the corresponding `User` row, and the segregation-of-duties checks that compare two officers (described under Wire Fraud Protection in §2.6) compare their `User.id` values.

The roles divide the closing into three non-overlapping spheres of authority. An `EscrowOfficer` owns the agreement lifecycle — drafting purchase agreements, activating them, taking and confirming earnest money deposits, drafting and delivering the Closing Disclosure, recording the buyer's acknowledgement of that disclosure, submitting wire instructions, performing the voice callback on those wires, queuing disbursements, opening the 1031 exchange account and identifying its replacement property, and executing the final close. A `TitleAgent` owns title work — ordering the title search, completing it with a list of defects, resolving any material defects, and issuing the title insurance policy. A `ComplianceOfficer` owns the compliance gates — recording the CC&R review, locking the wire instructions (different person than the officer who verified them), rejecting wire instructions, issuing clear-to-close, registering new users, and operating the test-driving clock endpoints. Specific endpoint authorisations are summarised in §4.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; a request outside this range is rejected with `ERR_INVALID_REQUEST`. The default `offset` is 0, its minimum is 0, and a negative `offset` (like a `limit`/`offset` that does not parse as an integer) is rejected with `ERR_INVALID_REQUEST`. Results are ordered by `created_at` ascending — chronologically, in the order they were recorded. The list endpoint's response envelope places `limit`, `offset`, `total_count`, and `has_more` inside `meta`, and the actual resource array in `data`.

### 2.4. Common Resource Properties, Timestamps, and Versioning

Every resource that the system writes carries an `id` field of type string. The `id` is a server-minted UUID with no type prefix — the client never supplies it on create, and a value such as `"agr_..."` or `"escrow_..."` is not used.

Most resources also carry three system fields. The `created_at` field is the UTC instant the row was inserted, formatted as an ISO 8601 timestamp with three fractional digits (millisecond precision, trailing `Z`). The `updated_at` field is the UTC instant of the most recent mutation, in the same format, refreshed on every state transition and every field change. The `version` field is an integer that begins at 1 and increments by exactly 1 every time the row mutates; it is the optimistic concurrency token described in §2.7.

Two resources are exceptions. The `CCRReview` resource is append-only: it carries `id` and `created_at`, but it carries neither `updated_at` nor `version` because no field on it is ever rewritten after creation. The `User` resource is likewise immutable once registered — it carries `id` and `created_at` but neither `updated_at` nor `version`.

A handful of status enumerations declare values that the workflows in §3 do not currently drive into, but which remain part of the contract for completeness and future extension. The `EarnestMoneyDeposit.status` enumeration includes `FORFEITED` (reserved for the buyer-default forfeiture path); `TitleInsurancePolicy.status` includes `VOIDED` (reserved for policy rescission); `ClosingDisclosure.status` includes the terminal `EXPIRED` (reserved for stale disclosure expiry); and `Disbursement.status` includes `REVERSED` (reserved for post-disbursement reversal). No endpoint in §4 drives a row into any of these four values today, but a returned `status` field on the relevant resource must accept and emit these exact strings if the underlying row carries them.

### 2.5. Monetary Precision, Time, and Tiered Rounding

All money flows through the system as integer cents. No monetary field is denominated in dollars, and no monetary field admits a fractional cent. Where a calculation involves a per-dollar rate (for example, the title insurance premium below), the cents amount is converted to dollars only at the formula boundary, the per-tier slice is rounded half up to whole cents, and the four slice values are summed to produce the final cents amount; there is no secondary rounding on the sum.

All wall-clock fields — `created_at`, `updated_at`, `issued_at`, `earliest_consummation_at`, `acknowledged_at`, `identification_deadline`, `exchange_deadline`, `identified_at`, `callback_verified_at`, `relinquished_closing_date`, and `scheduled_closing_date` — are UTC instants in ISO 8601 form with three fractional digits. The Closing Disclosure waiting period is measured as whole-hour clock arithmetic from the disclosure's `issued_at` instant. The 1031 identification deadline is `relinquished_closing_date` plus 45 days, and the 1031 exchange deadline is `relinquished_closing_date` plus 180 days.

### 2.6. Wire Fraud Protection and Segregation of Duties

Every wire instruction passes through a deliberately slow, two-person control before any money may move against it. When wire instructions for a party are first submitted (carrying `beneficiary_bank_name`, `beneficiary_account_last4`, `routing_number`, and the wire's `party` enum, which is one of `BUYER`, `SELLER`, `LENDER`, or `EXCHANGE_ACCOMMODATOR`), the instruction enters status `PROVIDED`. From there, the `EscrowOfficer` performs a voice callback to the beneficiary at the phone number on file, records the call with the request fields `verifier_id` and `voice_callback_reference`, and advances the instruction to `VERIFIED`. The system stamps `voice_callback_completed` to `true`, `callback_verified_at` to the current UTC clock, and `callback_verifier_id` to the acting `X-User-ID`. The `verifier_id` field in the request body must equal the acting `X-User-ID` — an officer cannot record a callback on behalf of someone else.

The lock that follows must be performed by a different officer. A `ComplianceOfficer` locking the wire compares their `X-User-ID` to the stored `callback_verifier_id`; if they are equal, the lock is rejected with `ERR_WIRE_SOD_VIOLATION` (HTTP 409). This is the segregation-of-duties anchor — the verifier cannot lock their own callback. Only a wire instruction in `LOCKED` status may be the destination of any `Disbursement`, and the clear-to-close gate (§3) refuses to advance until every wire instruction belonging to the agreement is `LOCKED`.

A wire instruction may also be rejected by a `ComplianceOfficer` at any time before it locks; rejection is a terminal state. When rejection is performed on a wire that was already `VERIFIED`, the compensating action clears the callback evidence: `voice_callback_completed` is reset to `false`, and both `callback_verified_at` and `callback_verifier_id` are cleared. This is deliberate — rejection is terminal for that wire's `id`, but the reset ensures the audit trail records that the prior verification no longer carries authority.

### 2.7. Optimistic Concurrency Control

Two write endpoints in this API are gated by optimistic concurrency control against a parent resource's `version` field; every other write endpoint is unguarded.

Creating a new `ClosingDisclosure` requires the request body to carry `expected_agreement_version`, an integer the client last observed on the target `PurchaseAgreement`. If that value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). The motivating scenario is a second officer who has already attached a Closing Disclosure to the same agreement — an attachment that legitimately starts the agreement's three-day clock and is permitted to supersede earlier drafts. A client whose view of the agreement predates that attachment is therefore stale, and the create is rejected before it can clobber the in-flight disclosure.

Issuing a `TitleInsurancePolicy` requires the request body to carry `expected_title_search_version`, an integer the client last observed on the target `TitleSearch`. If that value does not equal the title search's current `version`, the request is rejected with `ERR_STALE_TITLE_SEARCH_VERSION` (HTTP 412). The motivating scenario is a `TitleAgent` who has re-completed the same search (rewriting the defect list) between the issuing client's read and write — without the OCC check, the policy would attach to a stale defect snapshot. Each successful OCC-pinned write also bumps the parent's `version` by exactly one, so two strictly sequential requests against the same parent yield exactly one success and one `412`.

No other endpoint in the system carries `expected_<parent>_version`, and no other endpoint emits a 412 stale-version error.

### 2.8. Nested Path Resolution

Wherever a URL contains a path-templated `id`, the server resolves the segment to its target row before any business check runs. Any path id that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404). Foreign-key fields appearing in a request body (for example, the `agreement_id` on a Closing Disclosure create, the `escrow_account_id` on an earnest money deposit, or the `wire_instruction_id` on a disbursement) are likewise resolved against their target type before any business check runs; a foreign key that does not resolve is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.9. Cascade Semantics and Compensating Actions

A small number of business events cascade across multiple resources within the same transaction. When earnest money is confirmed and the agreement crosses its funding threshold, the cascade is: `EarnestMoneyDeposit.status` flips from `PENDING` to `CONFIRMED`; `PurchaseAgreement.earnest_money_received_cents` is recomputed; if the new total reaches or exceeds `earnest_money_required_cents` and the agreement is in `ACTIVE`, the agreement transitions to `UNDER_CONTRACT` and the escrow account transitions from `OPEN` to `FUNDED`. Both the agreement and the escrow account have their `version` bumped, and both have their `updated_at` refreshed.

When the close is executed, every queued disbursement on the escrow flips to `DISBURSED` in the order described under §3, the escrow account transitions through `FUNDED` → `DISBURSED` → `CLOSED` inside the same transaction (so its `version` increments by exactly two, from the two state writes), and any associated `ExchangeAccount` flips from `IDENTIFIED` to `COMPLETED`. When the agreement is terminated, every relevant earnest money deposit flips to `REFUNDED` and one refund `Disbursement` is emitted per deposit. These cascades are not optional and not configurable — they are part of the same transaction that drives the parent state change, and a failure inside any cascading write aborts the whole transaction.

### 2.10. Validation Priority

When a single request would fail multiple validations, the system evaluates them in a fixed priority order and surfaces the highest-ranking failure. Authentication (the presence and validity of `X-User-Role`, raising `ERR_UNAUTHENTICATED`) is evaluated first, then authorisation against the role table (raising `ERR_FORBIDDEN`), then existence of every path-templated `id` (raising `ERR_NOT_FOUND` left-to-right), then existence of every foreign-key field in the request body (raising `ERR_FK_NOT_FOUND`). State preconditions are next: the from-state check against the relevant state machine (raising `ERR_INVALID_STATE`), then the optimistic-concurrency checks of §2.7 (raising `ERR_STALE_AGREEMENT_VERSION` or `ERR_STALE_TITLE_SEARCH_VERSION`), then the three-day disclosure wait (raising `ERR_CD_THREE_DAY_NOT_ELAPSED`), then the wire segregation-of-duties check (raising `ERR_WIRE_SOD_VIOLATION`).

Business-safety and compliance checks rank above business-referential checks, and both rank above business-temporal, business-constraint, and business-fiscal checks. The wire-not-locked checks (`ERR_WIRE_NOT_LOCKED` on a queued disbursement, `ERR_WIRE_NOT_LOCKED` on clear-to-close, `ERR_BUYER_WIRE_NOT_LOCKED` on terminate), and the reissue-not-material check (`ERR_CD_REISSUE_NOT_MATERIAL`) all fall under business-safety. Below them lie the business-referential checks (`ERR_TITLE_NOT_INSURABLE`, `ERR_CD_NOT_ACKNOWLEDGED`, `ERR_CCR_NOT_ACKNOWLEDGED`), then the temporal deadline (`ERR_EXCHANGE_ID_DEADLINE_PASSED`), then the business constraints (`ERR_EXCHANGE_ROUTING_REQUIRED`, `ERR_INVALID_AMOUNT`, `ERR_PRICE_OUT_OF_RANGE`), then the fiscal sufficiency check at close (`ERR_INSUFFICIENT_ESCROW_FUNDS`). Catch-all body-shape errors (`ERR_INVALID_REQUEST`) are last.

The practical effect is that an unauthorised caller never sees a 404 (they receive 403 first), a missing path id never surfaces as a state error, a wire-fraud failure outranks a fiscal sufficiency failure, and a request that would fail both `ERR_INVALID_AMOUNT` and the catch-all body shape check surfaces the more specific code.

## 3. Business Logic & Workflows

### 3.1. Agreement Lifecycle: From Draft Through Funding

A closing begins when an `EscrowOfficer` creates a `PurchaseAgreement`. The create takes the buyer and seller legal names (`buyer_name`, `seller_name`), the `property_address`, the contract price (`purchase_price_cents`), the required earnest money deposit (`earnest_money_required_cents`), the target close date (`scheduled_closing_date`, a UTC instant whose date semantic carries a fixed time component of midnight), and optionally an `exchange_account_id` that, when present, declares the transaction is a 1031 like-kind exchange and routes seller proceeds via a qualified intermediary instead of to the seller directly. The contract price must be at least 100,000 cents and at most 1,000,000,000,000 cents (one trillion cents, or ten billion dollars) — values outside this range are rejected with `ERR_PRICE_OUT_OF_RANGE`. The `earnest_money_required_cents` must be non-negative; a negative value is rejected with `ERR_INVALID_REQUEST`. The new agreement lands in `DRAFT` with `version` 1, `status` `DRAFT`, `earnest_money_received_cents` of zero, and `terminated_reason` null.

Activation moves the agreement from `DRAFT` to `ACTIVE`. This is the moment escrow opens: in the same transaction the system auto-creates exactly one `EscrowAccount` whose `agreement_id` points to the new agreement and whose `escrow_officer_id` is the activating officer's `X-User-ID`. The escrow account lands in `OPEN` with `balance_cents` of zero; thereafter `balance_cents` is maintained as the sum of `amount_cents` across all `CONFIRMED` earnest money deposits on the escrow minus all `DISBURSED` disbursements, so it is recomputed (and refreshed on the escrow row) whenever a deposit is confirmed and whenever disbursements settle at close. Activation requires that `buyer_name`, `seller_name`, `property_address`, `purchase_price_cents`, `earnest_money_required_cents`, and `scheduled_closing_date` are all non-null on the agreement; if any is missing the activation is rejected with `ERR_INVALID_STATE` because the precondition for the `DRAFT → ACTIVE` transition is not met.

With the agreement in `ACTIVE` (or `UNDER_CONTRACT` — deposits may still be created and confirmed after funding; from any other agreement status the create is rejected with `ERR_INVALID_STATE`), earnest money may be taken. Each deposit carries an `escrow_account_id`, an `amount_cents` (which must be strictly greater than zero; a non-positive amount is rejected with `ERR_INVALID_AMOUNT`), and a `depositor_role` of either `BUYER` or `BUYERS_AGENT`, indicating whose hand the funds came from. A new deposit lands in `PENDING`. When the funds clear at the originating bank, the officer confirms the deposit, supplying a `confirmation_reference` in the request body; the deposit advances from `PENDING` to `CONFIRMED`. Confirmation is the trigger for the agreement's funding event. The system recomputes `earnest_money_received_cents` as the sum of `amount_cents` across every `CONFIRMED` deposit on the agreement; if that sum reaches or exceeds `earnest_money_required_cents` while the agreement is in `ACTIVE`, the agreement transitions to `UNDER_CONTRACT`, the escrow account transitions from `OPEN` to `FUNDED`, and both rows have their `version` bumped by one (see §2.9 for the full cascade).

### 3.2. Title Search and Insurance

While earnest money funds, a `TitleAgent` works the title side. Ordering a title search captures the `agreement_id` and creates a row in `ORDERED`. The search may only be ordered while the agreement is in `ACTIVE` or `UNDER_CONTRACT`. The agent later completes the search by supplying a `defects` array — a list whose elements describe each title defect with a `kind`, a `severity` of `MINOR` or `MATERIAL`, and a `description`; completion likewise requires the linked agreement to be in `ACTIVE` or `UNDER_CONTRACT`, otherwise it is rejected with `ERR_INVALID_STATE`. An empty array is the conventional way to record a clean title. Completion advances the search from `ORDERED` to `COMPLETED`, persists the array, and recomputes `has_material_defect`, which becomes `true` if and only if at least one element has `severity` equal to `MATERIAL` and the search is not yet `RESOLVED`.

Resolution closes the search out. Even a clean title (no material defects) must be resolved to advance: resolution is required regardless of whether the search currently carries a material defect. If `has_material_defect` is `true` at the moment of resolution, the request body must include a non-empty `resolution_notes`; resolution then rewrites every `MATERIAL` severity to `MINOR` in the stored defects array and recomputes `has_material_defect` accordingly (which is then `false`). If `has_material_defect` is `false` at the moment of resolution, `resolution_notes` may be omitted. Resolution moves the search from `COMPLETED` to `RESOLVED`, and `RESOLVED` is terminal — a subsequent retitle requires a new search row.

Issuing a `TitleInsurancePolicy` is the title agent's culminating act. The request carries the `title_search_id` of the search to insure and the `expected_title_search_version` that gates the OCC check described in §2.7. The referenced search must be in status `RESOLVED` with `has_material_defect` of `false`; otherwise the issuance is rejected with `ERR_TITLE_NOT_INSURABLE`. Issuance creates the policy in `ISSUED` with `version` 1, sets `coverage_amount_cents` equal to the linked agreement's `purchase_price_cents` at the instant of issuance, and computes `premium_cents` per the marginal-tier formula below.

The premium is tiered on the purchase price in dollars. The price is sliced at three break-points — 100,000 dollars, 500,000 dollars, and 1,000,000 dollars — yielding four tiers with successively lower per-dollar rates: 0.00450 per dollar for the first 100,000 dollars (the cents-equivalent break is 10,000,000 cents), 0.00400 per dollar for the portion from 100,000 dollars up to 500,000 dollars (cents break at 50,000,000), 0.00350 per dollar for the portion from 500,000 dollars up to 1,000,000 dollars (cents break at 100,000,000), and 0.00300 per dollar for any portion above 1,000,000 dollars. The amount that falls inside each tier is multiplied by that tier's per-dollar rate (after converting the slice from cents to dollars by dividing by 100), the resulting per-tier cent value is rounded half up to a whole cent, and the four rounded slices are then summed to produce the final `premium_cents`. There is deliberately no secondary rounding step on that sum — the per-tier rounding is the canonical rounding step, and "round once at the end" yields a measurably different cent value on certain prices.

The premium has one variant. The standard variant (the formula as written) applies by default. The lender-concurrent variant applies if and only if the agreement already carries at least one `WireInstruction` whose `party` is `LENDER` and whose status is anything other than `REJECTED`. In that case, after the per-tier sum has been computed, the result is reduced by 15 percent (a multiplier of 0.15 is subtracted from the unit factor, equivalently the sum is multiplied by 0.85), and that reduced amount is then rounded half up to a whole cent to yield the final `premium_cents`. This discount is the simultaneous-issue rebate that the title industry has always offered when the title premium and the lender's policy are issued concurrently. An OCC-pinned issuance also bumps the parent search's `version` by exactly one, which is what makes the OCC race deterministic — two strictly sequential issuance attempts against the same search yield exactly one success and one `ERR_STALE_TITLE_SEARCH_VERSION`.

### 3.3. CC&R Review and the Compliance Officer's Acknowledgement

A `ComplianceOfficer` records the CC&R review for the property in a single append-only entry. The review carries the `agreement_id`, the `hoa_name` (or null if the property is not subject to a homeowners' association), a `restrictions_summary` summarising the covenants, conditions and restrictions reviewed, and the boolean `buyer_acknowledged` that captures whether the buyer has explicitly accepted those restrictions. The review is immutable once recorded — there is no update or delete — and the only way to record a change is to append a new review row. The clear-to-close gate in §3.5 requires at least one such review with `buyer_acknowledged` of `true` (it does not additionally enforce that exactly one exists).

### 3.4. Closing Disclosure and the Three-Day Clock

The Closing Disclosure (CD) is the single biggest compliance artefact in a real estate closing, and its workflow deliberately mirrors the federally-mandated waiting period.

A draft CD is created by an `EscrowOfficer` against the agreement once that agreement is in `UNDER_CONTRACT`; this is a state precondition (raising `ERR_INVALID_STATE`) and is evaluated before the §2.7 OCC check, so an agreement not in `UNDER_CONTRACT` is rejected with `ERR_INVALID_STATE` even when `expected_agreement_version` is also stale. The create request carries the `agreement_id`, the `expected_agreement_version` for the OCC check, the loan terms — `cd_apr_bps` (the annual percentage rate in basis points), `cd_total_loan_amount_cents`, `cd_monthly_payment_cents`, the `cd_product_type` enum which is one of `FIXED`, `ARM`, `IO`, or `BALLOON`, and `cd_prepayment_penalty`, a boolean. The new disclosure lands in `DRAFT` with `version` 1, `issued_at` unset, `earliest_consummation_at` unset, and `acknowledged_at` null. The successful create also bumps the agreement's `version` by one.

Delivering the draft to the buyer advances it from `DRAFT` to `DELIVERED`. Delivery stamps `issued_at` to the current UTC clock and computes `earliest_consummation_at` as `issued_at` plus exactly 72 hours of clock time. (The federal three-business-day rule is simplified to a 72-hour wall-clock period for this benchmark; a real implementation would compute business days, but the contract here is whole-hour clock arithmetic from the delivery instant.) Delivery is only allowed while the disclosure is in `DRAFT` and the agreement is in `UNDER_CONTRACT`; either precondition failing is rejected with `ERR_INVALID_STATE`.

A delivered CD may be reissued if a material change occurs to the loan terms. Reissue accepts optional fields `cd_apr_bps`, `cd_product_type`, and `cd_prepayment_penalty` on the request body. The reissue is rejected with `ERR_CD_REISSUE_NOT_MATERIAL` unless the change is material under the following rule, evaluated against the current stored CD: the absolute difference between the request's `cd_apr_bps` and the current `cd_apr_bps` is at least 12 basis points (so an absolute delta of 12 bps is material; an absolute delta of 11 bps is not), or the request's `cd_product_type` differs from the current value, or `cd_prepayment_penalty` changes specifically from `false` to `true`. These three are the only triggers for re-clocking; a change to `cd_total_loan_amount_cents`, to `cd_monthly_payment_cents`, or to `cd_prepayment_penalty` from `true` to `false`, never re-clocks. When the change is material, the supplied fields are written, the disclosure advances from `DELIVERED` to `REISSUED`, `issued_at` is re-stamped to the current UTC clock, and `earliest_consummation_at` is recomputed as the new `issued_at` plus 72 hours — restarting the three-day clock from scratch.

Acknowledgement is the buyer's confirmation that the disclosure has been read. The endpoint advances the CD from `DELIVERED` (or from `REISSUED`, which is treated identically for acknowledgement purposes) to `ACKNOWLEDGED`. It is gated on time: the current UTC clock must be at or after `earliest_consummation_at`. Acknowledging on the 72-hour mark itself is allowed; strictly earlier is rejected with `ERR_CD_THREE_DAY_NOT_ELAPSED` (HTTP 409). Acknowledgement stamps `acknowledged_at` to the current UTC clock. The reissue-then-acknowledge path uses the re-stamped `earliest_consummation_at`, which is what makes reissue a real reset rather than a cosmetic rename.

### 3.5. Wire Instructions, Disbursements, and the Closing Itself

While the title and CD workflows are in progress, the escrow officer collects wire instructions from every party who will either receive or send money at close. Each `WireInstruction` belongs to the agreement and carries a `party` of `BUYER`, `SELLER`, `LENDER`, or `EXCHANGE_ACCOMMODATOR`; the bank details (`beneficiary_bank_name`, `beneficiary_account_last4`, `routing_number`) describe where the money goes. The two-person callback-and-lock control of §2.6 then advances each instruction through `PROVIDED` → `VERIFIED` → `LOCKED`, or terminates it in `REJECTED` if the wire fails verification.

Disbursements are queued against the escrow account at any point before close. A queued disbursement carries an `escrow_account_id`, a `wire_instruction_id` (the destination — which must reference a wire instruction whose status is `LOCKED`, otherwise the queue is rejected with `ERR_WIRE_NOT_LOCKED`), a `purpose` of `SELLER_PROCEEDS`, `LENDER_PAYOFF`, `TITLE_PREMIUM`, `EXCHANGE_FUNDS`, or `EARNEST_REFUND`, and an `amount_cents` strictly greater than zero. The disbursement lands in `QUEUED` with `version` 1. There is a special routing rule for 1031 exchanges: if the agreement carries a non-null `exchange_account_id`, a queued disbursement with `purpose` of `SELLER_PROCEEDS` is rejected with `ERR_EXCHANGE_ROUTING_REQUIRED` — under 1031 routing the seller's funds must be queued as `EXCHANGE_FUNDS` instead.

Clear-to-close is the compliance officer's go/no-go decision. Advancing the agreement from `UNDER_CONTRACT` to `CLEARED_TO_CLOSE` requires all of the following preconditions to hold concurrently (each gate is satisfied by the existence of at least one matching row — the system does not additionally enforce that exactly one such row exists): at least one `TitleSearch` exists for the agreement with status `RESOLVED` and `has_material_defect` of `false`; at least one `TitleInsurancePolicy` exists in status `ISSUED` whose underlying search traces back to the agreement; at least one `CCRReview` exists for the agreement with `buyer_acknowledged` of `true`; at least one `ClosingDisclosure` exists in status `ACKNOWLEDGED`; the current UTC clock is at or after that disclosure's `earliest_consummation_at`; and every `WireInstruction` belonging to the agreement is in status `LOCKED`. A missing CD acknowledgement raises `ERR_CD_NOT_ACKNOWLEDGED`; a missing CC&R acknowledgement raises `ERR_CCR_NOT_ACKNOWLEDGED`; any unlocked wire raises `ERR_WIRE_NOT_LOCKED`; the title gate failures surface as `ERR_INVALID_STATE` (because the agreement's `UNDER_CONTRACT → CLEARED_TO_CLOSE` precondition is not met). These gates are evaluated after the `UNDER_CONTRACT` from-state check, in the order: the wire-lock check (`ERR_WIRE_NOT_LOCKED`) first, then the CD-acknowledged check (`ERR_CD_NOT_ACKNOWLEDGED`), then the CC&R-acknowledged check (`ERR_CCR_NOT_ACKNOWLEDGED`), and the two title gates (`ERR_INVALID_STATE`) last.

Closing the agreement advances it from `CLEARED_TO_CLOSE` to `CLOSED` and runs the disbursement waterfall. The fiscal-sufficiency check fires first: the escrow account's `balance_cents` must be at least the sum of `amount_cents` across every `QUEUED` disbursement on that escrow; if not, the close is rejected with `ERR_INSUFFICIENT_ESCROW_FUNDS` and nothing changes. The waterfall then iterates over every `QUEUED` disbursement on the escrow account in `created_at` ascending order (oldest first). When two disbursements share the same `created_at` down to the millisecond, the tie is broken by lexicographic order of the `purpose` enum — that is, `EARNEST_REFUND` ranks before `EXCHANGE_FUNDS`, `EXCHANGE_FUNDS` before `LENDER_PAYOFF`, `LENDER_PAYOFF` before `SELLER_PROCEEDS`, and `SELLER_PROCEEDS` before `TITLE_PREMIUM`. The disbursement's `id` is forbidden as a tie-break input — order is purely chronological with a deterministic enum tiebreak.

For each disbursement in that order, if the running remaining balance is at least the disbursement's `amount_cents`, the disbursement advances from `QUEUED` to `DISBURSED`, its `version` increments by one, and the remaining balance is reduced by `amount_cents`. The arithmetic is in integer cents throughout; there is no rounding inside the waterfall. If at any point the remaining balance is strictly less than the next disbursement's amount, the entire close fails with `ERR_INSUFFICIENT_ESCROW_FUNDS` and the transaction aborts — no partial disbursement, no partial state change. (In practice the fiscal-sufficiency pre-check at the start of close prevents this from happening, but the waterfall maintains the same invariant inside the loop as a defence-in-depth.) The compensating-invariant is that the sum of `amount_cents` across queued disbursements at entry equals the sum across disbursed disbursements at exit, and the escrow account's `balance_cents` at exit equals its `balance_cents` at entry minus that sum. As the close transaction completes, the escrow account transitions from `FUNDED` through `DISBURSED` to `CLOSED` (so its `version` increments by exactly two, since two state writes happen back-to-back); if `exchange_account_id` on the agreement is non-null, the linked `ExchangeAccount` transitions from `IDENTIFIED` to `COMPLETED`; and the agreement itself completes in `CLOSED`.

### 3.6. Termination and the Earnest Refund Path

A purchase agreement may be terminated by an `EscrowOfficer` from one of two from-states, advancing it to the terminal `TERMINATED` status. From `ACTIVE` (i.e., before the agreement has reached `UNDER_CONTRACT`), termination requires only that the request body's `terminated_reason` is non-empty. The compensating action flips every `PENDING` earnest money deposit on the agreement's escrow to `REFUNDED`, transitions the escrow from `OPEN` to `CLOSED`, sets `terminated_reason` on the agreement, and bumps both the escrow's and the agreement's `version` by one each.

From `UNDER_CONTRACT`, termination is reserved for the unresolved-material-defect scenario: the agreement's `TitleSearch` must currently carry `has_material_defect` of `true`. (If the search has already been resolved — material defects downgraded to minor and `has_material_defect` flipped back to `false` — there is no unresolved defect to terminate against, and the request is rejected.) The `terminated_reason` must again be non-empty. The compensating action flips every `CONFIRMED` earnest money deposit to `REFUNDED` (this is the buyer-protection clause: confirmed deposits return to the buyer once a material defect blocks the deal), transitions the escrow from `FUNDED` to `CLOSED`, and bumps both versions.

For each earnest money deposit that flips to `REFUNDED` in either from-state, the system emits one `Disbursement` with `version` 1, `purpose` of `EARNEST_REFUND`, `amount_cents` equal to that deposit's `amount_cents`, and `wire_instruction_id` pointing to the agreement's `BUYER` wire instruction in status `LOCKED`. Each emitted refund disbursement lands in `QUEUED` status — it is recorded as a queued payment against the escrow and is not itself driven to `DISBURSED` within the termination transaction. Per-deposit, not aggregated — one refund disbursement per deposit, with the cent amount copied exactly; there is no rounding because the amounts are integer cents throughout. Refund disbursements are processed in `created_at` ascending order of the underlying deposit, with a tie-break (when two deposits share `created_at` to the millisecond) by lexicographic order of `depositor_role` — `BUYER` before `BUYERS_AGENT`. The deposit's `id` is forbidden as a tie-break input. The compensating invariant is that the sum of `amount_cents` across deposits flipping to `REFUNDED` equals the sum of `amount_cents` across the refund disbursements emitted in the same transaction.

If at least one deposit will flip to `REFUNDED` and no `BUYER` wire instruction for this agreement is currently in `LOCKED`, the termination is rejected with `ERR_BUYER_WIRE_NOT_LOCKED` (HTTP 409). The buyer's verified destination must exist before the system will route any refund — this is the same wire-fraud principle that gates the close, applied to the refund path. This check is conditional on there being refunds to route: when there is no deposit in the relevant status to refund, the termination proceeds (escrow → `CLOSED`, agreement → `TERMINATED`) without requiring a locked `BUYER` wire and emits no refund disbursements.

### 3.7. The 1031 Exchange Track

When the seller is deferring capital gains under Internal Revenue Code §1031, the seller establishes a like-kind exchange before the relinquished property's close. The platform models this with an `ExchangeAccount` resource. An `EscrowOfficer` opens the exchange account by providing the `taxpayer_name` (the seller's name as it appears on the federal return), the `qualified_intermediary_name` (the QI institution that will hold the exchange funds), and the `relinquished_closing_date` (the UTC instant that the relinquished property closed, which anchors both downstream deadlines). On creation the account lands in `OPEN` with `replacement_property_identified` of `false`, `identified_at` of null, `identification_deadline` set to `relinquished_closing_date` plus 45 days, and `exchange_deadline` set to `relinquished_closing_date` plus 180 days.

The seller has 45 days from the relinquished closing to identify candidate replacement properties in writing. The identify action carries a `replacement_property_address` (which must be non-empty) and advances the account from `OPEN` to `IDENTIFIED`. The action is allowed only while the current UTC clock is at or before `identification_deadline` — equality is allowed (an identification on the last day is valid), strictly later is rejected with `ERR_EXCHANGE_ID_DEADLINE_PASSED`. Because identify is a related write, the synchronous deadline evaluation of the next paragraph runs first, before the `OPEN` from-state precondition is checked: an `OPEN` account whose `identification_deadline` is already strictly past (with `replacement_property_identified` still `false`) is auto-transitioned to `FAILED` by that evaluation, after which the identify is rejected with `ERR_INVALID_STATE` for the failed from-state rather than `ERR_EXCHANGE_ID_DEADLINE_PASSED`. The dedicated `ERR_EXCHANGE_ID_DEADLINE_PASSED` code is therefore surfaced only when the account is still `OPEN` after that evaluation and the deadline check rejects it. The action sets `replacement_property_identified` to `true`, stamps `identified_at` to the current UTC clock, and bumps the account's `version` by one.

Two automatic transitions to `FAILED` also exist, each evaluated synchronously when the system observes the relevant deadline (typically on a read or a related write). On a related write the evaluation is performed at the start, before that write's own from-state precondition is checked, so a deadline-driven `FAILED` transition can pre-empt the write and surface as `ERR_INVALID_STATE` for the failed from-state. From `OPEN`, the account flips to `FAILED` when the current UTC clock is strictly greater than `identification_deadline` and `replacement_property_identified` is still `false` — no replacement was identified in time. From `IDENTIFIED`, the account flips to `FAILED` when the current UTC clock is strictly greater than `exchange_deadline` — the replacement was identified but the closing never happened within 180 days. Both transitions bump the account's `version` by one.

The reciprocal success transition is system-driven: while the account is in `IDENTIFIED`, when the corresponding `PurchaseAgreement` transitions to `CLOSED` inside the close transaction described in §3.5, the exchange account flips from `IDENTIFIED` to `COMPLETED` in the same transaction, provided the current UTC clock is at or before `exchange_deadline`. Inside the close transaction, the system also verifies that the exchange account is in `OPEN` or `IDENTIFIED` and the clock is at or before `exchange_deadline`; if not, the close itself is rejected with `ERR_INVALID_STATE`.

The 1031 routing rule weaves the exchange track back into the disbursement workflow. When an agreement's `exchange_account_id` is non-null, the seller's funds at close cannot go directly to the seller — they must route through the qualified intermediary. The system enforces this at queue-time: a disbursement with `purpose` of `SELLER_PROCEEDS` against an agreement that carries an exchange account is rejected with `ERR_EXCHANGE_ROUTING_REQUIRED`. The escrow officer must instead queue the same amount with `purpose` of `EXCHANGE_FUNDS` and direct it to the `EXCHANGE_ACCOMMODATOR` wire instruction. The waterfall's arithmetic is otherwise unchanged; the routing constraint is purely a queue-time validation.

### 3.8. Test-Driving the Clock

Two administrative endpoints expose the server's logical clock for end-to-end testing. A `ComplianceOfficer` may pin the clock to an explicit ISO 8601 instant by supplying a `to_iso8601` value (whole-second precision), or advance the clock by a duration in `seconds`. These are capability-only endpoints — they do not name a state transition; their effect is purely temporal. Subsequent reads observe the new clock, which is how the 72-hour disclosure wait, the 45-day identification deadline, and the 180-day exchange deadline are exercised deterministically. The exchange account's `FAILED` transitions in §3.7 are evaluated synchronously against the current clock, so advancing the clock past either deadline and then reading the account is the canonical way to trigger them.

## 4. Endpoint Definitions

All endpoints return JSON in the envelope of §2.2. Endpoints that create a new resource return HTTP 201 with the new resource in `data`; endpoints that modify an existing resource or fetch one return HTTP 200; list endpoints return HTTP 200 with an array in `data` and pagination fields in `meta`. Authentication failures return 401, authorisation failures 403, missing path or foreign-key targets 404, state and business preconditions 409, optimistic-concurrency failures 412, and validation failures 422.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/purchase-agreements` | Create a new purchase agreement in `DRAFT` | EscrowOfficer |
| GET | `/purchase-agreements/{id}` | Fetch a purchase agreement | EscrowOfficer, TitleAgent, ComplianceOfficer |
| GET | `/purchase-agreements` | List purchase agreements, paginated and filterable | EscrowOfficer, TitleAgent, ComplianceOfficer |
| POST | `/purchase-agreements/{id}/activate` | Activate the agreement; auto-creates the escrow account | EscrowOfficer |
| POST | `/purchase-agreements/{id}/clear-to-close` | Issue clear-to-close once all gates pass | ComplianceOfficer |
| POST | `/purchase-agreements/{id}/close` | Execute the close and run the disbursement waterfall | EscrowOfficer |
| POST | `/purchase-agreements/{id}/terminate` | Terminate the agreement; refunds earnest money via disbursements | EscrowOfficer |
| GET | `/escrow-accounts/{id}` | Fetch an escrow account | EscrowOfficer, ComplianceOfficer |
| GET | `/escrow-accounts` | List escrow accounts | EscrowOfficer, ComplianceOfficer |
| POST | `/earnest-money-deposits` | Create a pending earnest money deposit on an escrow account | EscrowOfficer |
| POST | `/earnest-money-deposits/{id}/confirm` | Confirm the deposit; may bubble the agreement to under-contract | EscrowOfficer |
| GET | `/earnest-money-deposits` | List earnest money deposits | EscrowOfficer, ComplianceOfficer |
| GET | `/earnest-money-deposits/{id}` | Fetch an earnest money deposit | EscrowOfficer, ComplianceOfficer |
| POST | `/title-searches` | Order a title search | TitleAgent |
| POST | `/title-searches/{id}/complete` | Complete the search and record defects | TitleAgent |
| POST | `/title-searches/{id}/resolve` | Resolve the search; downgrade material defects | TitleAgent |
| GET | `/title-searches` | List title searches | TitleAgent, EscrowOfficer, ComplianceOfficer |
| GET | `/title-searches/{id}` | Fetch a title search | TitleAgent, EscrowOfficer, ComplianceOfficer |
| POST | `/title-insurance-policies` | Issue title insurance against a resolved search (OCC-gated) | TitleAgent |
| GET | `/title-insurance-policies/{id}` | Fetch a title insurance policy | TitleAgent, EscrowOfficer, ComplianceOfficer |
| GET | `/title-insurance-policies` | List title insurance policies | TitleAgent, EscrowOfficer, ComplianceOfficer |
| POST | `/ccr-reviews` | Record a CC&R review (append-only) | ComplianceOfficer |
| GET | `/ccr-reviews` | List CC&R reviews | ComplianceOfficer, EscrowOfficer |
| GET | `/ccr-reviews/{id}` | Fetch a CC&R review | ComplianceOfficer, EscrowOfficer |
| POST | `/closing-disclosures` | Create a closing disclosure in `DRAFT` (OCC-gated) | EscrowOfficer |
| POST | `/closing-disclosures/{id}/deliver` | Deliver the disclosure and stamp the 72-hour clock | EscrowOfficer |
| POST | `/closing-disclosures/{id}/reissue` | Reissue on material change; restart the 72-hour clock | EscrowOfficer |
| POST | `/closing-disclosures/{id}/acknowledge` | Acknowledge the disclosure once the clock has elapsed | EscrowOfficer |
| GET | `/closing-disclosures/{id}` | Fetch a closing disclosure | EscrowOfficer, ComplianceOfficer |
| GET | `/closing-disclosures` | List closing disclosures | EscrowOfficer, ComplianceOfficer |
| POST | `/wire-instructions` | Submit wire instructions for a party | EscrowOfficer |
| POST | `/wire-instructions/{id}/callback-verify` | Record the voice callback and advance to verified | EscrowOfficer |
| POST | `/wire-instructions/{id}/lock` | Lock verified wire instructions (different officer than the verifier) | ComplianceOfficer |
| POST | `/wire-instructions/{id}/reject` | Reject wire instructions | ComplianceOfficer |
| GET | `/wire-instructions/{id}` | Fetch a wire instruction | EscrowOfficer, ComplianceOfficer |
| GET | `/wire-instructions` | List wire instructions | EscrowOfficer, ComplianceOfficer |
| POST | `/disbursements` | Queue a disbursement against an escrow account | EscrowOfficer |
| GET | `/disbursements` | List disbursements | EscrowOfficer, ComplianceOfficer |
| GET | `/disbursements/{id}` | Fetch a disbursement | EscrowOfficer, ComplianceOfficer |
| POST | `/exchange-accounts` | Open a 1031 exchange account | EscrowOfficer |
| POST | `/exchange-accounts/{id}/identify` | Identify the replacement property | EscrowOfficer |
| GET | `/exchange-accounts/{id}` | Fetch an exchange account (may synchronously fail on elapsed deadlines) | EscrowOfficer, ComplianceOfficer |
| GET | `/exchange-accounts` | List exchange accounts | EscrowOfficer, ComplianceOfficer |
| POST | `/users` | Register a user with a role | ComplianceOfficer |
| GET | `/users/{id}` | Fetch a user | EscrowOfficer, TitleAgent, ComplianceOfficer |
| GET | `/users` | List users | ComplianceOfficer |
| POST | `/_clock/set` | Set the server's mock UTC clock to an explicit instant | ComplianceOfficer |
| POST | `/_clock/advance` | Advance the server's mock UTC clock by a duration in seconds | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_STALE_TITLE_SEARCH_VERSION` | 412 |
| `ERR_CD_THREE_DAY_NOT_ELAPSED` | 409 |
| `ERR_CD_REISSUE_NOT_MATERIAL` | 422 |
| `ERR_WIRE_SOD_VIOLATION` | 409 |
| `ERR_WIRE_NOT_LOCKED` | 409 |
| `ERR_BUYER_WIRE_NOT_LOCKED` | 409 |
| `ERR_TITLE_NOT_INSURABLE` | 409 |
| `ERR_CD_NOT_ACKNOWLEDGED` | 409 |
| `ERR_CCR_NOT_ACKNOWLEDGED` | 409 |
| `ERR_EXCHANGE_ID_DEADLINE_PASSED` | 409 |
| `ERR_EXCHANGE_ROUTING_REQUIRED` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_PRICE_OUT_OF_RANGE` | 422 |
| `ERR_INSUFFICIENT_ESCROW_FUNDS` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
