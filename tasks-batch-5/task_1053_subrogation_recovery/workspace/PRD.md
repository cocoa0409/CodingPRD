# Subrogation Recovery API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Subrogation & Recovery Vendor API, the system of record for a recovery vendor that pursues at-fault third parties on behalf of its insurance-carrier clients. When a carrier pays a loss to its insured, it retains the right to recover that outlay — plus the insured's deductible — from the party who caused the loss. The vendor takes referral of these claims, assesses the adverse party's liability, issues formal demands, escalates disputed demands into intercompany arbitration, negotiates settlements, books the money that comes back, returns the insured's deductible on a make-whole basis, and bills the carrier a commission on what it recovers.

The platform models this end-to-end lifecycle as a set of peer resources — carriers, adverse parties, claims, demands, arbitrations, settlements, recovery payments, deductible reimbursements, and commission statements — linked by reference and coordinated through a strict set of state machines. Two forces dominate the design. First, **time**: statutes of limitation, demand-response windows, arbitration-filing windows, and hearing schedules are all driven by a server-controlled logical clock rather than wall-clock time, so that deadline behaviour is deterministic and testable. Second, **money conservation and control**: every dollar recovered is allocated through a fixed waterfall, every reversal is compensated exactly, settlement approval is bounded by managerial authority and separated from the proposer's hands, and commission is computed under one of two contractual bases per carrier. The sections below define the global contracts that apply to every endpoint, then narrate the business workflows in detail, and finally enumerate the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity in which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes six roles, spelled exactly as follows: `RecoverySpecialist`, `RecoveryManager`, `CarrierUser`, `FinanceOfficer`, `System`, and `Any`. `Any` denotes that any authenticated role may read the resource in question; the read (GET) endpoints are open to all authenticated principals.

Three of these roles are opaque operator identities and three are worth spelling out individually:

- When `X-User-Role` is `RecoverySpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures the actor — for example as `proposed_by_user_id` on a `Settlement` the specialist proposes — but never compares it to any entity's `id`.
- When `X-User-Role` is `RecoveryManager`, `X-User-ID` is likewise an opaque operator identifier. The server records it where a transition writes the acting manager — for example as `approved_by_user_id` on an approved `Settlement` — but does not equate it to any entity's `id`.
- When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier used for the financial operations (recording, clearing, and reversing recovery payments; disbursing reimbursements; opening commission statements). It is not compared to any entity's `id`.
- When `X-User-Role` is `System`, `X-User-ID` is an opaque automation identifier used only to drive the logical clock and the system sweeps it triggers.
- When `X-User-Role` is `CarrierUser`, `X-User-ID` is the `id` of the acting `Carrier`. Ownership checks compare a resource's carrier reference to `X-User-ID`: a `CarrierUser` may act on a `Claim` only when that claim's `carrier_id` equals `X-User-ID`. A carrier-owned action on a claim the caller does not own — referring, withdrawing, accepting a settlement for, or attaching a document to it — is rejected with `ERR_NOT_CLAIM_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp — refreshed on every mutation — and an integer `version` that starts at 1 and increments by one on every mutation of the resource.

One entity is an exception. A `ClaimDocument` is append-only evidence: it is immutable once created and therefore carries only `id` and `created_at`. It has no `updated_at` and no `version` field.

Because carrier-facing reads must reflect live financial state, the ledger fields maintained on a `Claim` — `final_recovered_cents`, `deductible_reimbursed_cents`, `carrier_recovered_cents`, and `accrued_commission_cents` — are computed properties that the server keeps current as payments clear and reverse; each such recomputation is itself a mutation that refreshes the claim's `updated_at` and increments its `version`.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integer counts of cents; there are no fractional-cent stored values. Wherever a calculation divides — applying a basis-point commission rate or a liability percentage — the intermediate result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger magnitude). Each calculation section below states the exact operands and the order in which rounding is applied; the order matters, because rounding per line before summing can differ from summing then rounding.

### 2.6. The Logical Clock and Deadline Sweeps

The server does not read wall-clock time. Instead it maintains a **logical clock** whose startup default is `2026-07-01T00:00:00Z`. All system-recorded instants — a claim's `referral_date`, a demand's `issued_at`, an arbitration's `filed_at`, a payment's `received_at`, a reimbursement's `disbursed_at`, and a demand's `disputed_at` — are stamped from this clock, and all deadline comparisons are made against it.

An administrative, test-driving capability advances the clock to a supplied `to_iso8601` instant. Advancing the clock immediately runs a deadline sweep with two parts, evaluated against the new clock value. First, for every `Claim` still in a non-terminal status (`REFERRED`, `LIABILITY_ASSESSED`, `DEMAND_ISSUED`, or `ARBITRATION`), if the clock now reaches or passes the claim's `statute_deadline`, the claim moves to `STATUTE_EXPIRED` together with the cascades described in §3.9. Second, for every `Demand` still in `ISSUED` status whose `outcome` is still unset, if the clock now reaches or passes that demand's `response_due_at`, the demand moves to `EXPIRED`. All deadline comparisons in this system are inclusive of the deadline instant: a resource is considered expired *at* the deadline, not only strictly after it.

### 2.7. Nested Resource Retrieval

Several paths address a child resource beneath a parent — for example a claim's demands or a claim's documents. Path identifiers are validated left-to-right: the server confirms each referenced resource exists in path order before validating request-body foreign keys, and the first identifier that does not resolve produces `ERR_NOT_FOUND`. This ordering applies uniformly to reads, creates, and transitions, so that a request naming a non-existent parent is rejected before any child lookup or business rule runs.

### 2.8. Cascading Consistency and Ledger Integrity

Many operations mutate more than one resource. When they do, every secondary effect is part of the same logical operation and every touched resource independently has its `updated_at` refreshed and its `version` incremented. The claim ledger is the clearest example: clearing a recovery payment does not merely change that payment's status, it also advances four running totals on the parent claim and may create a downstream reimbursement and promote the claim's status. §3.6 and §3.9 enumerate each cascade precisely. The governing principle is conservation — money booked by a clearing operation is exactly reversed by the corresponding compensation when a cleared payment is later reversed, and no running total is allowed to drift.

### 2.9. Optimistic Concurrency Control on Settlement Proposals

Proposing a settlement is guarded by optimistic concurrency control on the parent claim. A request to propose a `Settlement` against a claim must carry `expected_claim_version`, a non-optional field holding the `version` of the `Claim` the client last observed. If `expected_claim_version` does not equal the claim's current `version`, the proposal is rejected with `ERR_STALE_CLAIM_VERSION` at HTTP 412. This matters because a new proposal legitimately supersedes any prior `PROPOSED` settlement on the same claim — the prior proposal is moved to `SUPERSEDED` and the claim's `version` is bumped — so a client acting on a stale claim view would otherwise silently overwrite a proposal it never saw. Requiring the observed version forces the client to re-read before it can supersede. No other endpoint takes a version field; OCC applies only to settlement proposal.

### 2.10. Segregation of Duties and Managerial Authority

Settlement control is deliberately split. The `RecoverySpecialist` who proposes a settlement is recorded in `proposed_by_user_id`; approval is a `RecoveryManager` action, and the approving manager's `X-User-ID` must differ from `proposed_by_user_id`. An attempt by the proposer to approve their own settlement is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval is additionally bounded by authority: a manager may approve only when the proposed `settled_amount_cents` does not exceed the managerial authority ceiling of 5,000,000 cents (that is, $50,000); a larger amount is rejected with `ERR_EXCEEDS_SETTLEMENT_AUTHORITY`.

### 2.11. Validation Ordering

When several checks apply to a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is: (1) presence and validity of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) the role's permission for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); (3) existence of every referenced resource, validated left-to-right in the path and then for body foreign keys (`ERR_NOT_FOUND`); (4) carrier ownership for `CarrierUser` claim actions — refer, withdraw, accept, and add-document (`ERR_NOT_CLAIM_OWNER`); (5) well-formedness of the request body — correct types, valid enum members, positive amounts where required, a `liability_pct` between 0 and 100 inclusive, and `hearing_start` strictly before `hearing_end` (`ERR_INVALID_REQUEST`); (6) segregation of duties on settlement approval (`ERR_SEGREGATION_OF_DUTIES`); (7) that the target resource is in a state permitting the requested transition (`ERR_INVALID_STATE`); (8) referential arbitration eligibility checks (`ERR_ADVERSE_NOT_ARBITRABLE` / `ERR_DEMAND_NOT_DISPUTED`); (9) temporal deadline and window checks (`ERR_STATUTE_EXPIRED` / `ERR_ARBITRATION_WINDOW_CLOSED` / `ERR_DEMAND_WINDOW_OPEN` / `ERR_HEARING_WINDOW_CONFLICT`); (10) settlement approval authority (`ERR_EXCEEDS_SETTLEMENT_AUTHORITY`); (11) the payment-versus-settlement fiscal ceiling (`ERR_PAYMENT_EXCEEDS_SETTLEMENT`); (12) other business-constraint checks such as carrier suspension on referral and statement openness on finalize (`ERR_CARRIER_SUSPENDED` / `ERR_STATEMENT_NOT_OPEN`); and (13) the optimistic-concurrency check on settlement proposal (`ERR_STALE_CLAIM_VERSION`). Lower-numbered checks take precedence: for instance, a missing header is reported before any permission or existence check, and an existence failure is reported before any state or temporal check.

## 3. Business Logic & Workflows

### 3.1. Onboarding Carriers and Adverse Parties

A `RecoveryManager` onboards each client insurer as a `Carrier`, supplying the insurer's `name`, its `naic_code` (the NAIC company code), and the vendor's recovery commission rate in basis points as `commission_rate_bps` (for example, 2500 basis points expresses a 25% rate; the value must be between 1 and 10000 inclusive). The manager may also state the `commission_basis` under which the carrier is billed — either `GROSS` or `NET`. When omitted, `commission_basis` defaults to `NET`, meaning commission is charged on recovery net of the deductible returned to the insured; the meaning of each basis is spelled out in §3.8. A newly created carrier begins in `status` `ACTIVE`. A manager may later suspend a carrier, moving its `status` to `SUSPENDED`; a suspended carrier can no longer receive new claim referrals.

An `AdverseParty` — the at-fault party the claim is pursued against — is created by a `RecoverySpecialist` or a `RecoveryManager`. It records the party's `name`, the `adverse_carrier_name` of that party's own insurer, a boolean `is_arbitration_eligible` flag that is true only when the adverse insurer is a signatory to the intercompany arbitration forum (this flag gates whether arbitration may ever be filed), and `policy_limit_cents`, the adverse policy limit, which must be zero or greater and which caps the recoverable estimate.

### 3.2. Claim Referral and Liability Assessment

A claim enters the system when a `CarrierUser` (acting for their own carrier) or a `RecoverySpecialist` refers it. Referral supplies the `carrier_id` of the referring carrier, the `adverse_party_id` of the party to recover against, the carrier's external `claim_reference`, the `loss_date`, and three monetary figures: `paid_loss_cents` (what the carrier paid its insured, excluding the deductible), `deductible_cents` (the insured's deductible, to be recovered on a make-whole priority), and `total_damages_cents` (the full claimed damages, against which liability is applied). Referral also supplies the `statute_deadline`, the statute-of-limitations instant beyond which the claim can no longer be pursued. On referral the claim is stamped with a system `referral_date` taken from the logical clock and enters `status` `REFERRED`. A referral naming a carrier that is not `ACTIVE` is rejected with `ERR_CARRIER_SUSPENDED`. If a claim is referred with a `statute_deadline` already in the past, it is simply born expired for action purposes — such a claim was never swept and any action on it fails the statute check (`ERR_STATUTE_EXPIRED`) rather than being auto-transitioned.

Throughout a claim's life, a `RecoverySpecialist` or the owning `CarrierUser` may attach evidence to it as a `ClaimDocument`, supplying the `doc_type` — one of `POLICE_REPORT`, `ESTIMATE`, `POLICY`, `CORRESPONDENCE`, or `OTHER` — a `title`, and a `uri` pointing at the stored file or external link. Each document is tied to its claim by `claim_id` and, as noted in §2.4, is append-only and immutable once created. A `CarrierUser` may attach a document only to a claim their carrier owns.

Liability assessment is the specialist's first substantive step and moves the claim from `REFERRED` to `LIABILITY_ASSESSED`. The specialist supplies `liability_pct`, the assessed adverse-liability percentage, which must lie between 0 and 100 inclusive; the referring carrier must still be `ACTIVE`, and the logical clock must be before the `statute_deadline`, otherwise the action is rejected with `ERR_STATUTE_EXPIRED`. Assessment sets `liability_pct` and computes the claim's provisional recoverable estimate into `provisional_recoverable_cents`. That provisional figure is the **smallest** of three ceilings: the liability share, the adverse policy limit, and the carrier's out-of-pocket exposure. The liability share is `total_damages_cents` multiplied by `liability_pct` divided by 100, rounded half up to whole cents. The out-of-pocket exposure — the base exposure — is `paid_loss_cents` plus `deductible_cents`. The policy ceiling is the adverse party's `policy_limit_cents`. The provisional recoverable is whichever of these three is least. (This provisional estimate is forward-looking; the final recoverable figure, once a settlement is accepted, is simply the accepted amount, as described in §3.5.)

### 3.3. Demands and the Response Window

Once liability is assessed, the specialist issues a formal demand against the adverse party, which advances the claim to `DEMAND_ISSUED`. Issuing a demand is permitted while the claim is in `LIABILITY_ASSESSED` or already in `DEMAND_ISSUED` (a claim may carry successive demands). The specialist supplies `amount_demanded_cents`, which must be strictly greater than zero. A demand may be issued only if there is no existing demand for the claim that is still in `ISSUED` status with an open response window; attempting to issue while a prior demand's window is still open is rejected with `ERR_DEMAND_WINDOW_OPEN`. The logical clock must also be before the `statute_deadline`. On issuance the demand is stamped with `issued_at` from the clock, enters `status` `ISSUED`, and is given a `response_due_at` that is 30 days after `issued_at`; this instant is the exclusive end of the response window. A re-demand issued after a prior window has closed leaves the claim in `DEMAND_ISSUED` (the claim status cycles in place) while creating a fresh demand with its own 30-day window.

The adverse party's answer is captured by recording a response, supplying an `outcome` of either `HONORED` or `DISPUTED`. A response may be recorded only while the clock is still before the demand's `response_due_at`. Recording `HONORED` sets the demand's `outcome` and moves it from `ISSUED` to `HONORED`. Recording `DISPUTED` sets the `outcome`, moves the demand from `ISSUED` to `DISPUTED`, stamps `disputed_at` with the current clock value, and computes `arbitration_window_due_at` as 60 days after `disputed_at` — the instant before which any arbitration must be filed. If no response is recorded and the clock reaches or passes `response_due_at`, the next clock advance sweeps the demand from `ISSUED` to `EXPIRED` (see §2.6).

### 3.4. Intercompany Arbitration

When a demand is disputed, the specialist may escalate the claim into intercompany arbitration, moving the claim from `DEMAND_ISSUED` to `ARBITRATION`. Filing requires that the adverse party's `is_arbitration_eligible` be true — otherwise `ERR_ADVERSE_NOT_ARBITRABLE` — and that at least one demand on the claim is in `DISPUTED` status — otherwise `ERR_DEMAND_NOT_DISPUTED`. Filing must occur while the clock is before that disputed demand's `arbitration_window_due_at`; a filing at or after that instant is rejected with `ERR_ARBITRATION_WINDOW_CLOSED`. The clock must also be before the `statute_deadline`. The filing supplies the `forum` code (for example, the intercompany forum code) and creates an `Arbitration` stamped with `filed_at`, in `status` `FILED`.

The arbitration then proceeds through hearing scheduling and negotiation rounds. Scheduling the hearing moves the arbitration from `FILED` to `AWAITING_RESPONSE`; the specialist supplies `hearing_start` and `hearing_end`, which are recorded on the arbitration. The window is valid only if `hearing_start` is strictly before `hearing_end`. Furthermore, no other arbitration tied to the *same adverse party* (reached through its claim) may already hold a hearing window within 7 days of the requested `[hearing_start, hearing_end]` span; a conflict within that 7-day buffer is rejected with `ERR_HEARING_WINDOW_CONFLICT`.

Negotiation is cyclic. Filing a round appends an entry to the arbitration's append-only `rounds` log and increments its computed `round_count`. Each entry records a sequential `round_no`, the `filer`, the `filed_at` instant, and the `note` supplied on the request. From `AWAITING_RESPONSE`, filing a round moves the arbitration to `RESPONSE_FILED`; from `RESPONSE_FILED`, filing a rebuttal round moves it back to `AWAITING_RESPONSE`, opening the next round — the two states toggle for as many rounds as the parties exchange. A `RecoveryManager` closes the matter by deciding it, which sets `award_amount_cents` to the forum's decision and moves the arbitration to `DECIDED`. A decision may be issued from either `RESPONSE_FILED` or `AWAITING_RESPONSE` (the latter being a decision on default).

### 3.5. Settlement: Proposal, Approval, and Acceptance

A settlement is the negotiated resolution of the claim. A `RecoverySpecialist` proposes a `Settlement` against a claim, supplying the proposed `settled_amount_cents` (strictly greater than zero) and `expected_claim_version`. The proposal is subject to the optimistic-concurrency rule of §2.9: `expected_claim_version` must equal the claim's current `version`, or the proposal is rejected with `ERR_STALE_CLAIM_VERSION` at HTTP 412. On success the settlement is created in `status` `PROPOSED`, the proposer's `X-User-ID` is recorded as `proposed_by_user_id`, any prior `PROPOSED` settlement on the same claim is moved to `SUPERSEDED`, and the claim's `version` is incremented by one.

A `RecoveryManager` then approves or rejects the proposal. Approval moves the settlement from `PROPOSED` to `APPROVED` and records the manager's `X-User-ID` as `approved_by_user_id`; it is gated by the segregation-of-duties rule (the approver's `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`) and by the authority ceiling (`settled_amount_cents` must not exceed 5,000,000 cents, else `ERR_EXCEEDS_SETTLEMENT_AUTHORITY`), both described in §2.10. Rejection simply moves the settlement from `PROPOSED` to `REJECTED`.

Acceptance is the carrier's prerogative. A `CarrierUser` accepts an approved settlement, which moves the settlement from `APPROVED` to `ACCEPTED`. Acceptance is permitted only when the accepting `CarrierUser`'s `X-User-ID` matches the claim's `carrier_id` and when the claim is currently in `DEMAND_ISSUED` or `ARBITRATION`. Acceptance drives the claim to `SETTLED` and sets the claim's `settled_amount_cents` to the settlement's `settled_amount_cents` — this accepted amount is the claim's final recoverable figure. When the accepted claim was in `ARBITRATION`, acceptance additionally renders any live arbitration moot: every `Arbitration` for that claim in `FILED`, `AWAITING_RESPONSE`, or `RESPONSE_FILED` is cascaded to `WITHDRAWN`.

### 3.6. Recovery Payments and the Allocation Waterfall

Money recovered from the adverse party is booked as recovery payments against a settled claim, and this is `FinanceOfficer` territory. A payment is recorded with its gross `amount_cents` (strictly greater than zero) and stamped with `received_at`; it enters `status` `RECEIVED`. Recording is bounded fiscally: the cumulative total of already-cleared payments plus this new amount must not exceed the claim's `settled_amount_cents`, or the request is rejected with `ERR_PAYMENT_EXCEEDS_SETTLEMENT` at HTTP 422.

Clearing a payment is where allocation happens; a payment may be cleared only while its claim is in `SETTLED` or `RECOVERED`. Clearing moves the payment from `RECEIVED` to `CLEARED` and runs the recovery waterfall, which splits the gross `amount_cents` into three buckets filled in a fixed order — deductible first, then commission, then carrier. Concretely: the outstanding insured deductible is the claim's `deductible_cents` minus the deductible already committed by prior cleared payments on that claim; `alloc_deductible_cents` (bucket one) is the smaller of the payment's `amount_cents` and that outstanding deductible. The remainder after the deductible bucket is `amount_cents` minus `alloc_deductible_cents`. From that remainder, `alloc_commission_cents` (bucket two) is the carrier's `commission_rate_bps` divided by 10000, multiplied by the remainder, rounded half up to whole cents. `alloc_carrier_cents` (bucket three) is the remainder minus `alloc_commission_cents`. By construction the three buckets sum exactly to the gross `amount_cents`.

Clearing then cascades onto the claim ledger. The claim's `final_recovered_cents` is increased by the payment's gross `amount_cents`; its `carrier_recovered_cents` is increased by `alloc_carrier_cents`; and its `accrued_commission_cents` is increased by `alloc_commission_cents`. (Note that the deductible bucket is *committed* against the claim's outstanding deductible at this point, but the claim's `deductible_reimbursed_cents` total is not increased until the reimbursement is actually disbursed — see §3.7.) Next, if the claim's `final_recovered_cents` now reaches or exceeds its `settled_amount_cents`, the claim is promoted from `SETTLED` to `RECOVERED`. Finally, if this payment's `alloc_deductible_cents` is greater than zero, the system creates a `DeductibleReimbursement` in `status` `PENDING` whose `amount_cents` equals that `alloc_deductible_cents`, linking it to the funding payment via `recovery_payment_id` and to the claim via `claim_id`.

A payment can also be reversed, again by a `FinanceOfficer`. Reversing a payment that has not yet cleared simply moves it from `RECEIVED` to `BOUNCED` with no ledger effect. Reversing a `CLEARED` payment moves it to `REVERSED` and compensates every booking exactly: the claim's `final_recovered_cents` is decreased by the payment's `amount_cents`, its `carrier_recovered_cents` is decreased by `alloc_carrier_cents`, and its `accrued_commission_cents` is decreased by `alloc_commission_cents`. If the claim was `RECOVERED` and, after this compensation, its `final_recovered_cents` falls below its `settled_amount_cents`, the claim is demoted from `RECOVERED` back to `SETTLED`. And the `DeductibleReimbursement` funded by this payment is clawed back: whether it was `PENDING` or `DISBURSED`, it moves to `CLAWED_BACK`, and if it had already been `DISBURSED`, the claim's `deductible_reimbursed_cents` is decreased by that reimbursement's `amount_cents`.

### 3.7. Returning the Deductible to the Insured

The make-whole promise to the insured is fulfilled through deductible reimbursements. Each `DeductibleReimbursement` is created by the system when a payment clears with a positive deductible allocation (§3.6); it is never created directly by a client. It records the `claim_id` it belongs to, the `recovery_payment_id` of the clearing payment that funded it, and an `amount_cents` equal to that payment's `alloc_deductible_cents`, and it begins in `status` `PENDING`.

A `FinanceOfficer` disburses the reimbursement to the insured, moving it from `PENDING` to `DISBURSED`. Disbursement is permitted only while the funding recovery payment is still `CLEARED`. On disbursement the reimbursement is stamped with `disbursed_at`, and the claim's `deductible_reimbursed_cents` is increased by the reimbursement's `amount_cents`. As noted above, if the funding payment is later reversed, a disbursed reimbursement is clawed back to `CLAWED_BACK` and the claim's `deductible_reimbursed_cents` is decreased by the same `amount_cents`; a still-pending reimbursement simply moves to `CLAWED_BACK` with no ledger change.

### 3.8. Commission Statements and Reporting

The vendor bills each carrier through commission statements. A `FinanceOfficer` opens a `CommissionStatement` for a carrier, supplying a `period_label` (for example, a quarter label such as 2026-Q3). Opening the statement sweeps every `Claim` belonging to that carrier that is in `RECOVERED` status at sweep time into the statement's frozen `lines`, ordered by each claim's `created_at` ascending. Each entry in `lines` records the source `claim_id`, that claim's `net_recovery_cents`, and its `commission_cents`. The statement opens in `status` `OPEN` with `total_commission_cents` starting at 0.

The commission owed on a single recovered claim depends on the carrier's `commission_basis`. Under the `GROSS` basis, commission is the carrier's `commission_rate_bps` divided by 10000, multiplied by the claim's gross recovery `final_recovered_cents`, rounded half up to whole cents. Under the `NET` basis (the default), commission is `commission_rate_bps` divided by 10000, multiplied by the claim's gross recovery `final_recovered_cents` reduced by its `deductible_reimbursed_cents`, again rounded half up. The applicable basis is the carrier's `commission_basis`: `GROSS` uses the gross variant, otherwise the net variant is used.

A `RecoveryManager` finalizes the statement, moving it from `OPEN` to `FINALIZED`. Finalization is permitted only when the statement is `OPEN` and its `lines` are non-empty; a statement that is not open, or one with no lines, is rejected with `ERR_STATEMENT_NOT_OPEN`. Finalization freezes the lines and sets `total_commission_cents`. The total is computed by rounding each line's commission to whole cents first and then summing those already-whole per-line `commission_cents` — per-claim rounding strictly precedes summation, because summing raw fractional commissions and rounding once at the end can differ by a cent and is not used here. Alternatively, a manager may void an open statement by finalizing it with `void` set to true, which moves the statement from `OPEN` to `VOID`.

### 3.9. Withdrawal, Statute Expiry, and Terminal Cascades

A `CarrierUser` who owns a claim may withdraw the referral at any pre-recovery stage, which moves the claim to `WITHDRAWN`; ownership is checked as the carrier's `X-User-ID` matching the claim's `carrier_id`. Withdrawal from `REFERRED` or `LIABILITY_ASSESSED` has no downstream effects. Withdrawal from `DEMAND_ISSUED` cascades any open demand (in `ISSUED` or `DISPUTED`) to `WITHDRAWN`. Withdrawal from `ARBITRATION` cascades any open demand to `WITHDRAWN` and cascades every arbitration in `FILED`, `AWAITING_RESPONSE`, or `RESPONSE_FILED` to `WITHDRAWN`.

Statute expiry is system-driven. When the logical clock is advanced (§2.6) to an instant that reaches or passes a non-terminal claim's `statute_deadline`, that claim is swept to `STATUTE_EXPIRED`. A claim expiring out of `DEMAND_ISSUED` cascades its open demand to `WITHDRAWN`; a claim expiring out of `ARBITRATION` cascades any arbitration in `FILED`, `AWAITING_RESPONSE`, or `RESPONSE_FILED` to `WITHDRAWN`. Claims in `REFERRED` or `LIABILITY_ASSESSED` expire without further cascades. The terminal statuses for a claim are `RECOVERED`, `WITHDRAWN`, and `STATUTE_EXPIRED`; a demand's terminal statuses are `HONORED`, `EXPIRED`, and `WITHDRAWN`; an arbitration's are `DECIDED` and `WITHDRAWN`; a settlement's are `ACCEPTED`, `REJECTED`, and `SUPERSEDED`; a recovery payment's are `CLEARED`, `REVERSED`, and `BOUNCED`; a reimbursement's are `DISBURSED` and `CLAWED_BACK`; and a commission statement's are `FINALIZED` and `VOID`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock control endpoint — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/subro/carriers` | Create a carrier (vendor client) | RecoveryManager |
| GET | `/subro/carriers/{carrier_id}` | Get a carrier | Any |
| POST | `/subro/carriers/{carrier_id}/suspend` | Suspend a carrier | RecoveryManager |
| POST | `/subro/adverse-parties` | Create an adverse party | RecoverySpecialist, RecoveryManager |
| GET | `/subro/adverse-parties/{adverse_party_id}` | Get an adverse party | Any |
| POST | `/subro/claims` | Refer a claim | CarrierUser, RecoverySpecialist |
| GET | `/subro/claims/{claim_id}` | Get a claim (ledger fields included) | Any |
| GET | `/subro/claims` | List claims | Any |
| POST | `/subro/claims/{claim_id}/assess-liability` | Assess adverse liability; sets provisional recoverable | RecoverySpecialist |
| POST | `/subro/claims/{claim_id}/withdraw` | Carrier withdraws the referral | CarrierUser |
| POST | `/subro/claims/{claim_id}/documents` | Attach a document to a claim | RecoverySpecialist, CarrierUser |
| GET | `/subro/claims/{claim_id}/documents` | List a claim's documents | Any |
| POST | `/subro/claims/{claim_id}/demands` | Issue a demand | RecoverySpecialist |
| GET | `/subro/demands/{demand_id}` | Get a demand | Any |
| GET | `/subro/demands` | List demands | Any |
| POST | `/subro/demands/{demand_id}/record-response` | Record adverse response to a demand | RecoverySpecialist |
| POST | `/subro/claims/{claim_id}/arbitrations` | File intercompany arbitration | RecoverySpecialist |
| GET | `/subro/arbitrations/{arbitration_id}` | Get an arbitration | Any |
| GET | `/subro/arbitrations` | List arbitrations | Any |
| POST | `/subro/arbitrations/{arbitration_id}/schedule-hearing` | Schedule the hearing window | RecoverySpecialist |
| POST | `/subro/arbitrations/{arbitration_id}/rounds` | File a filing/response round | RecoverySpecialist |
| POST | `/subro/arbitrations/{arbitration_id}/decide` | Forum issues a decision/award | RecoveryManager |
| POST | `/subro/claims/{claim_id}/settlements` | Propose a settlement (OCC on claim version) | RecoverySpecialist |
| GET | `/subro/settlements/{settlement_id}` | Get a settlement | Any |
| GET | `/subro/settlements` | List settlements | Any |
| POST | `/subro/settlements/{settlement_id}/approve` | Manager approves (SoD + authority boundary) | RecoveryManager |
| POST | `/subro/settlements/{settlement_id}/reject` | Manager rejects | RecoveryManager |
| POST | `/subro/settlements/{settlement_id}/accept` | Carrier accepts an approved settlement | CarrierUser |
| POST | `/subro/claims/{claim_id}/recovery-payments` | Record a recovery payment against a settled claim | FinanceOfficer |
| GET | `/subro/recovery-payments/{recovery_payment_id}` | Get a recovery payment (allocation fields included) | Any |
| GET | `/subro/recovery-payments` | List recovery payments | Any |
| POST | `/subro/recovery-payments/{recovery_payment_id}/clear` | Clear the payment: run waterfall, cascade to claim and reimbursement | FinanceOfficer |
| POST | `/subro/recovery-payments/{recovery_payment_id}/reverse` | Reverse a payment (compensation and claw-back) | FinanceOfficer |
| GET | `/subro/deductible-reimbursements/{deductible_reimbursement_id}` | Get a deductible reimbursement | Any |
| GET | `/subro/deductible-reimbursements` | List deductible reimbursements | Any |
| POST | `/subro/deductible-reimbursements/{deductible_reimbursement_id}/disburse` | Disburse the reimbursement to the insured | FinanceOfficer |
| POST | `/subro/carriers/{carrier_id}/commission-statements` | Create a commission statement; sweep RECOVERED claims | FinanceOfficer |
| GET | `/subro/commission-statements/{commission_statement_id}` | Get a commission statement (lines + total) | Any |
| GET | `/subro/commission-statements` | List commission statements | Any |
| POST | `/subro/commission-statements/{commission_statement_id}/finalize` | Finalize (compute total) or void a statement | RecoveryManager |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers the statute-and-window sweep | System |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_CLAIM_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ADVERSE_NOT_ARBITRABLE` | 409 |
| `ERR_DEMAND_NOT_DISPUTED` | 409 |
| `ERR_STATUTE_EXPIRED` | 409 |
| `ERR_ARBITRATION_WINDOW_CLOSED` | 409 |
| `ERR_DEMAND_WINDOW_OPEN` | 409 |
| `ERR_HEARING_WINDOW_CONFLICT` | 409 |
| `ERR_EXCEEDS_SETTLEMENT_AUTHORITY` | 409 |
| `ERR_CARRIER_SUSPENDED` | 409 |
| `ERR_STATEMENT_NOT_OPEN` | 409 |
| `ERR_PAYMENT_EXCEEDS_SETTLEMENT` | 422 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
