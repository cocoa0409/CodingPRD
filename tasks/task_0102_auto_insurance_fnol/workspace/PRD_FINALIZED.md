# Auto Insurance FNOL API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auto Insurance Claims API, the back-office system that carries an automobile loss from the moment it is reported through to final settlement and third-party recovery. The domain begins with a *first notice of loss* (FNOL): the instant a policyholder reports that a vehicle has been damaged. From there the claim must be checked against the governing policy, handed to a qualified adjuster, estimated for repair, and — when the damage is severe enough — declared a total loss rather than repaired. The system is fundamentally a **ledger reconciliation** engine wearing a claims-handling skin: every dollar that leaves the insurer (a settlement, a rental reimbursement) or returns to it (a subrogation recovery) is a signed entry against a per-claim cash ledger that must reconcile to the cent at all times.

Two characteristics make this domain unforgiving. First, a single claim follows one of two mutually exclusive economic paths — the repair path or the total-loss path — and the choice between them, driven by a repair-cost-to-value ratio, fans out into divergent settlement math, rental curtailment, and salvage handling. Second, the work is governed by a strict **segregation of duties**: the adjuster who writes the repair estimate may not be the same person who declares the vehicle a total loss, and only a supervisor may release money. The requirements below codify these constraints precisely, because in this domain a miscomputed cent or a duties violation is not a cosmetic defect but an audit failure.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint regardless of the business workflow it serves.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `ClaimsSupervisor`, `ClaimsAdjuster`, `TotalLossAdjuster`, and `SubrogationSpecialist`. A `ClaimsSupervisor` is the administrative and fiscal authority: they set up policies, coverages, and adjusters, assign adjusters to claims, settle and close claims, and are the sole authority permitted to void a disbursement. A `ClaimsAdjuster` is the front-line handler who files losses, verifies coverage, authors and submits repair estimates, computes rentals, and decides the repair disposition. A `TotalLossAdjuster` is a senior adjuster who authors total-loss evaluations and decides the total-loss disposition. A `SubrogationSpecialist` pursues third-party recovery on already-settled claims.

The meaning of `X-User-ID` depends on the acting role. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is the `id` of the acting `Adjuster`; ownership and authorship checks on any resource that references an `Adjuster` compare the resource's adjuster foreign-key field to `X-User-ID`. In particular, when a `ClaimsAdjuster` creates a repair estimate, the new estimate's `authored_by_adjuster_id` is set to `X-User-ID`, and the rule that "only the assigned adjuster may submit" compares the claim's `assigned_adjuster_id` to that same value. When `X-User-Role` is `TotalLossAdjuster`, `X-User-ID` is likewise the `id` of the acting `Adjuster`; the evaluation's `evaluated_by_adjuster_id` is set from it, and the segregation-of-duties comparison is made against it. When `X-User-Role` is `ClaimsSupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it but does not compare it to any entity's `id`. When `X-User-Role` is `SubrogationSpecialist`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in this system carries a server-minted `id` formatted as a UUID with no type prefix, and an immutable `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Every entity in this API also carries an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 and increases by one on each modification to the resource. There are no immutable-after-creation entities here; all of them — `Policy`, `Coverage`, `Adjuster`, `Claim`, `ClaimParty`, `CoverageVerification`, `RepairEstimate`, `TotalLossEvaluation`, `RentalReimbursement`, `SubrogationCase`, and `Disbursement` — expose the full `id` / `created_at` / `updated_at` / `version` quartet.

A recomputation of a derived field counts as a mutation. When a claim's `settlement_cents`, `disposition`, `total_disbursed_cents`, or `assigned_adjuster_id` changes, the claim's `updated_at` is refreshed. The `version` field, however, is advanced **only** by the four claim transitions that the workflow narrative explicitly calls out as version-bumping (assignment, disposition, and the two settle transitions); a pure ledger refresh triggered indirectly by a child entity (for example a rental approval or a subrogation resolution recomputing `total_disbursed_cents`) refreshes `updated_at` without itself being one of those bump points.

### 2.5. Nested and Reverse-Reachability Retrieval

Some read endpoints are addressed through a parent path segment — for example, listing the coverages of a policy, or the parties, coverage verifications, or disbursements of a claim. For any such path the system validates the path identifiers strictly left to right: the parent (the `Policy` or the `Claim`) must exist before any child collection is considered, and a missing parent yields `ERR_NOT_FOUND` for that parent before the child query runs. The remaining collections are reachable as flat lists filterable by their foreign key: claims by `policy_id` or `assigned_adjuster_id`, repair estimates by `claim_id` or `authored_by_adjuster_id`, total-loss evaluations by `claim_id` or `evaluated_by_adjuster_id`, rental reimbursements by `claim_id`, and subrogation cases by `claim_id` or `target_party_id`. Each of these list endpoints also accepts a `status` filter where the underlying entity carries a status. Disbursements for a claim are reachable both by `claim_id` and by `source_entity_id`, which pins the originating claim of the ledger entry.

### 2.6. Monetary Precision and Ratio Rounding

All monetary quantities in this system are stored and exchanged as **integer cents**; there is no sub-cent representation and no floating-point money. Aggregations of money (summing estimate lines, summing ledger entries) are therefore exact and require no rounding. Two derived quantities are not pure money and do require an explicit rounding rule. The total-loss ratio is a fractional number rounded to exactly four decimal places using round-half-up. The comparative-negligence recovery is computed by multiplying a cent amount by a fault percentage and is rounded to whole cents using round-half-up, applied exactly once at the end of the computation rather than at any intermediate step. Wherever a calculation pins an evaluation order, that order is mandatory and may not be reordered even when the arithmetic appears commutative.

### 2.7. Optimistic Concurrency Control on the Claim

Three claim-mutating operations are guarded by optimistic concurrency control keyed on the claim's `version`. Each of these requests must carry an `expected_claim_version` field holding the `version` the client last observed on the target claim. If `expected_claim_version` does not equal the claim's current `version` at the time the server processes the request, the operation is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), and no state change occurs.

The three guarded operations are: assigning an adjuster to a verified claim, deciding the claim's disposition, and settling the claim. The guard exists because each of these operations advances the claim's `version`, so a request that carries a `version` from before an earlier advance is acting on a snapshot that no longer reflects reality. For the disposition decision specifically, a stale view means the client is deciding against an estimate or evaluation snapshot that has since moved, so the write is refused until the client re-reads the claim. For assignment, a stale view means another assignment or a reopen has already mutated the claim, so the writer carrying the outdated `expected_claim_version` is refused. For settlement, because the disposition decision itself bumps the version, any settle request carrying a pre-disposition `version` is by definition stale and refused. Operations not in this set of three never take a version field.

### 2.8. The Per-Claim Cash Ledger

Each claim owns a running cash ledger materialized in the denormalized claim field `total_disbursed_cents` and queryable as a computed read. The ledger is the net sum, over every `Disbursement` for the claim whose `status` is `APPROVED`, of that disbursement's `amount_cents`. Disbursements in any other status — and there is exactly one other, `VOIDED` — are excluded from the sum. A `SETTLEMENT` disbursement and a `RENTAL` disbursement carry a positive (outbound) `amount_cents`; a `SUBROGATION_RECOVERY` disbursement carries a negative `amount_cents`, representing money flowing back to the insurer. The ledger is recomputed from scratch on every event that creates or voids an approved disbursement, and the entries are summed in `created_at` ascending order so the replay is deterministic. The governing invariant is cash conservation to the cent: a `SUBROGATION_RECOVERY` of negative X paired with the original settlement leaves the net reduced by exactly X, and voiding a disbursement restores `total_disbursed_cents` to precisely the value it held before that disbursement existed.

### 2.9. Segregation of Duties and Adjuster Licensing

This domain separates the people who can act on a claim. An adjuster's `license_tier` is either `STANDARD` or `SENIOR`, and only a `SENIOR`-tier adjuster may author a total-loss evaluation. Independently, the person who authored the active repair estimate may never be the person who declares the same claim a total loss: the evaluation's author and the submitted estimate's author must be different adjusters. These are two distinct guards with two distinct error codes, described in their workflow context below. Finally, the authority to move money — settling a claim, and voiding a disbursement — rests exclusively with the `ClaimsSupervisor`, separate from the line adjusters who compute the amounts.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Policies, Coverages, and Adjusters

Before any loss can be reported, a `ClaimsSupervisor` establishes the static reference data. A policy is created with a `policyholder_name`, a `policy_number` (which must be unique across all policies), an `effective_date`, and an `expiration_date` marking the coverage period, plus an optional `comparative_fault_rule`. The fault rule is one of `PURE`, `MODIFIED_50`, or `MODIFIED_51` and defaults to `MODIFIED_50` when omitted; it governs how the insured's own fault later reduces a third-party recovery. A newly created policy begins in `ACTIVE` status. A supervisor may later mark a policy `LAPSED` as an administrative correction; the third status value, `CANCELLED`, also exists, and only an `ACTIVE` policy provides coverage.

When a new policy is filed, the system guards against overlapping coverage for the same `policyholder_name`. Treat the policy's coverage period as the closed interval running from its `effective_date` through its `expiration_date` inclusive. A new policy is rejected with `ERR_POLICY_PERIOD_OVERLAP` if that closed interval overlaps the closed interval of any existing policy for the same `policyholder_name` whose `status` is either `ACTIVE` or `LAPSED` (a `CANCELLED` policy is ignored for this check). Overlap holds whenever the new policy's start is on or before the existing policy's end **and** the existing policy's start is on or before the new policy's end. Adjacency is treated as a collision here: touching endpoints do overlap, so a new policy's `effective_date` must fall strictly after the prior policy's `expiration_date`.

Within a policy, the supervisor adds coverage lines. A coverage names its parent through `policy_id`, declares a `coverage_type` of `COLLISION`, `COMPREHENSIVE`, or `RENTAL`, and sets a per-claim payout ceiling `limit_cents`. For collision and comprehensive coverages, a `deductible_cents` (defaulting to 0) is withheld from the gross loss; rental coverages carry a `deductible_cents` of 0. A rental coverage additionally specifies a per-day reimbursement ceiling `rental_daily_cap_cents` and a maximum number of reimbursable days `rental_max_days`, both of which default to 0 and are 0 for non-rental coverages. At most one coverage of a given `coverage_type` may exist per policy; a second coverage of the same type on the same policy is rejected with `ERR_DUPLICATE_COVERAGE`.

Adjusters are also created by the supervisor. An adjuster has a `full_name`, a `license_tier` that defaults to `STANDARD`, and an `active` flag defaulting to true that controls whether the adjuster may receive new assignments.

### 3.2. Filing the Loss and Verifying Coverage

A claim enters the world when a `ClaimsAdjuster` or `ClaimsSupervisor` files a first notice of loss against a policy. The filing payload carries the `policy_id`, the `loss_datetime` at which the loss occurred, the `loss_type` (`COLLISION` or `COMPREHENSIVE`, which selects the coverage that must apply), and the `vehicle_acv_cents` — the actual cash value of the vehicle at the time of loss. Two optional inputs round out the filing: `insured_fault_pct`, the insured party's own fault percentage between 0 and 100 inclusive (defaulting to 0), and `salvage_value_cents`, the salvage proceeds expected for a totaled vehicle (defaulting to 0 and only meaningful on the total-loss path). A new claim begins in `FNOL_SUBMITTED` status with `version` 1, a null `disposition`, a `settlement_cents` of 0, a `total_disbursed_cents` of 0, and a null `assigned_adjuster_id`. The claim also tracks a server-managed `status` and `disposition` throughout its life.

Coverage verification is the first consequential step, performed by a `ClaimsAdjuster`. Running verification examines three conditions: the parent policy must be `ACTIVE`; the loss instant must fall within the coverage window, meaning `loss_datetime` is at or after the policy's `effective_date` and strictly before its `expiration_date` (the window is closed on the left and open on the right); and a coverage row must exist on that policy whose `coverage_type` matches the claim's `loss_type` — a `COLLISION` loss matches a `COLLISION` coverage and a `COMPREHENSIVE` loss matches a `COMPREHENSIVE` coverage. When all three hold, the claim advances `FNOL_SUBMITTED → COVERAGE_VERIFIED` and the system records a `CoverageVerification` whose `outcome` is `VERIFIED` and whose `matched_coverage_type` is set to the matched coverage's type, with `denial_reason` left null. When at least one condition fails — the policy is not `ACTIVE`, or the loss falls outside the window, or no matching coverage exists — the claim instead moves `FNOL_SUBMITTED → COVERAGE_DENIED` and the recorded `CoverageVerification` has `outcome` `DENIED`, a null `matched_coverage_type`, and a `denial_reason` of `POLICY_INACTIVE`, `OUTSIDE_COVERAGE_WINDOW`, or `NO_MATCHING_COVERAGE` according to which condition failed. Each `CoverageVerification` names its claim through `claim_id`.

A denial is not the end of the road. `COVERAGE_DENIED` is non-terminal: a `ClaimsSupervisor` may reopen such a claim, moving it `COVERAGE_DENIED → REOPENED`, which clears the prior coverage-verification linkage so coverage may be assessed afresh. Reopening is permitted only while the claim is in `COVERAGE_DENIED`. From `REOPENED`, the same verification action runs again against the same three conditions and, on success, advances the claim `REOPENED → COVERAGE_VERIFIED`, recording a fresh `CoverageVerification` with `outcome` `VERIFIED`.

### 3.3. Assigning the Adjuster

Once coverage is verified, a `ClaimsSupervisor` assigns a handling adjuster, moving the claim `COVERAGE_VERIFIED → UNDER_REVIEW`. The assignment payload identifies the target through `adjuster_id` and carries the concurrency token `expected_claim_version`. The target adjuster's `active` flag must be true, and the claim must not already have an `assigned_adjuster_id` set. As described in the concurrency principle, `expected_claim_version` must match the claim's current `version` or the request is rejected with `ERR_STALE_CLAIM_VERSION`. On success the claim's `assigned_adjuster_id` is set to the target adjuster and the claim's `version` is incremented by one.

### 3.4. Building the Repair Estimate

With a claim `UNDER_REVIEW`, the assigned adjuster prepares the cost of repair. A `ClaimsAdjuster` creates a repair estimate naming its claim through `claim_id` and supplying `lines` — a list of estimate lines, each an object carrying a `description`, a `labor_cents`, and a `parts_cents`. On creation the estimate's `authored_by_adjuster_id` is recorded as the acting adjuster and its `status` begins as `DRAFT`. The estimate's `repair_total_cents` is computed as the sum, over every line, of that line's `labor_cents` plus its `parts_cents`; because all inputs are whole cents the sum is exact with no rounding, and all lines participate regardless of any status.

Submitting an estimate advances it `DRAFT → SUBMITTED` and makes it the active estimate used for disposition. Submission is restricted: the parent claim must be `UNDER_REVIEW`, and the estimate's `authored_by_adjuster_id` must equal the claim's `assigned_adjuster_id`, so that only the assigned adjuster may submit. Submission recomputes `repair_total_cents`. Crucially, an estimate's submission supersedes its predecessor: if another repair estimate for the same claim is already `SUBMITTED`, that earlier estimate is transitioned `SUBMITTED → SUPERSEDED` as a side effect of the new submission, leaving exactly one `SUBMITTED` estimate per claim at any time. `SUPERSEDED` is terminal for an estimate.

### 3.5. The Total-Loss Evaluation

When damage may exceed the worth of repairing the vehicle, a `TotalLossAdjuster` authors a total-loss evaluation. The evaluation names its claim through `claim_id` and accepts an optional `salvage_retained_by_insurer` flag, which defaults to true and records whether the insurer keeps the wrecked vehicle's salvage or hands it back to the insured. Authoring is gated: only a `SENIOR`-tier adjuster may author an evaluation, and an attempt by a non-senior adjuster is rejected with `ERR_SENIOR_TIER_REQUIRED`. On creation the evaluation snapshots two values frozen at evaluation time — `acv_cents`, a copy of the claim's `vehicle_acv_cents`, and `repair_total_cents`, a copy of the currently `SUBMITTED` repair estimate's `repair_total_cents` — and records its author in `evaluated_by_adjuster_id` as the acting adjuster.

From those snapshots the evaluation computes two derived fields. The `total_loss_ratio` is the snapshot `repair_total_cents` divided by the snapshot `acv_cents`, rounded to four decimal places half-up. The boolean `is_total_loss` is true when `total_loss_ratio` is at or above the total-loss threshold and false otherwise. That threshold is a repair-to-value ratio of 0.75: a ratio of exactly 0.7500 **is** a total loss because the boundary is inclusive, while a ratio of 0.7499 stays just below the boundary and remains on the repair path. The boundary comparison is at-or-above, never strictly-above.

### 3.6. Deciding the Disposition: The Fork

The pivotal moment in a claim's life is the disposition decision, taken while the claim is `UNDER_REVIEW`. The decision payload carries a `decision` field and the concurrency token `expected_claim_version`; in both branches a mismatch between `expected_claim_version` and the claim's current `version` is rejected with `ERR_STALE_CLAIM_VERSION`, and a successful decision increments the claim's `version` by one. The decision forks the claim down one of two divergent paths.

**The repair branch.** A `ClaimsAdjuster` may decide for repair, advancing the claim `UNDER_REVIEW → REPAIR_APPROVED`. This branch requires that exactly one repair estimate for the claim is in `SUBMITTED` status, and that no total-loss evaluation for the claim has `is_total_loss` true; if there is no single submitted estimate the request is rejected with `ERR_NO_SUBMITTED_ESTIMATE`. On success the claim's `disposition` is set to `REPAIR` and its `settlement_cents` is recomputed as the first-party repair payout. That payout starts from the gross repair cost — the `repair_total_cents` of the submitted estimate — withholds the matched coverage's `deductible_cents` (never letting the after-deductible figure fall below zero), and then caps the result at the matched coverage's `limit_cents`. Concretely the after-deductible amount is the greater of zero and the gross minus the deductible, and the settlement is the lesser of that after-deductible amount and the coverage limit. When the after-deductible amount is at or below the limit, the settlement equals gross minus deductible; when it exceeds the limit, the settlement equals the limit and the excess is the insured's own responsibility. The insured's own `insured_fault_pct` does **not** reduce this first-party payout.

**The total-loss branch.** A `TotalLossAdjuster` may decide for total loss, advancing the claim `UNDER_REVIEW → TOTAL_LOSS`. This branch requires that a total-loss evaluation for the claim exists with `is_total_loss` true — absent which the request is rejected with `ERR_NOT_A_TOTAL_LOSS` — and that the evaluation's `evaluated_by_adjuster_id` differs from the `authored_by_adjuster_id` of the submitted repair estimate, enforcing segregation of duties; a same-author collision is rejected with `ERR_SEGREGATION_OF_DUTIES`. On success the decision cascades in two hops. First, the claim's `disposition` is set to `TOTAL_LOSS` and its `settlement_cents` is recomputed as the first-party total-loss payout. That payout begins from the evaluation's snapshot `acv_cents`; if the evaluation's `salvage_retained_by_insurer` is true the claim's `salvage_value_cents` is subtracted (the insurer keeps the wreck), and if it is false no salvage is subtracted (the insured keeps the wreck, so the payout is higher by the salvage amount); the deductible is then withheld with a floor of zero; and finally the result is capped at the coverage `limit_cents`. The evaluation order is fixed and mandatory — salvage first, then deductible, then the limit cap — so the after-salvage figure is the base minus salvage, the after-deductible figure is the greater of zero and after-salvage minus the deductible, and the settlement is the lesser of after-deductible and the limit. Second, and as a transitive consequence of the disposition flipping to `TOTAL_LOSS`, every `PENDING` rental reimbursement on the claim is recomputed and curtailed (see the rental curtailment rule below).

These two checks specific to the total-loss decision are evaluated together with the universal guards in a fixed order that applies, in spirit, to every write across the system. The system first authenticates the caller (failing with `ERR_UNAUTHENTICATED`), then confirms the caller's role is permitted (`ERR_FORBIDDEN_ROLE`), then resolves all path- and body-referenced resources left to right (`ERR_NOT_FOUND` on the first missing one), then validates the request body — required fields present and well-typed, enum values within their declared set, and any `fault_pct` or `insured_fault_pct` within 0 through 100 inclusive — failing with `ERR_INVALID_REQUEST`. Only then does it confirm the target resource is in a state from which the requested transition is defined, rejecting an out-of-state request with `ERR_INVALID_STATE`; this state guard governs every transition endpoint in the system. After the state check comes the concurrency check on `expected_claim_version`, and only then the business gates — for the total-loss decision, segregation of duties before the not-a-total-loss check. This ordering ensures, for instance, that a stale-version refusal surfaces before a business-eligibility refusal.

### 3.7. Rental Reimbursement

Independent of the disposition path, a `ClaimsAdjuster` computes a rental reimbursement for the claim. The request names its claim through `claim_id` and supplies the rental window — `rental_start_date` (inclusive) and `rental_end_date` (exclusive) — together with the quoted `daily_rate_cents`. The window must be a positive interval: `rental_end_date` must be strictly after `rental_start_date`, or the request is rejected with `ERR_INVALID_RENTAL_INTERVAL`. Beyond positivity, a new rental may not collide with another rental already on the claim. Treat each rental's period as the half-open interval from its start (inclusive) to its end (exclusive). A new rental is rejected with `ERR_RENTAL_PERIOD_OVERLAP` if its half-open interval overlaps that of any existing `PENDING` or `APPROVED` rental on the same claim. Overlap holds when the new rental's start is strictly before the existing rental's end **and** the existing rental's start is strictly before the new rental's end; adjacency is allowed, so one rental ending exactly when another begins is not a collision.

On creation the system computes the reimbursement and the rental's `status` begins `PENDING`. The number of requested days is the duration of the half-open window divided by 86,400 seconds and rounded up to the next whole day. The applicable day cap is the rental coverage's `rental_max_days`; but if the parent claim's `disposition` is `TOTAL_LOSS`, the day cap is lowered to the smaller of `rental_max_days` and five days, because once the insured has been paid out for the vehicle they are no longer repairing it. The `reimbursable_days` is the smaller of the requested days and the applicable day cap. The per-day amount is the smaller of the quoted `daily_rate_cents` and the coverage's `rental_daily_cap_cents` — the per-day cap is applied to each day before multiplying, never after summing. The final `reimbursement_cents` is `reimbursable_days` multiplied by that capped per-day amount. This same computation is what re-runs during the total-loss cascade described above: when a claim flips to `TOTAL_LOSS`, each still-`PENDING` rental is recomputed with the five-day-curtailed cap, lowering both its `reimbursable_days` and its `reimbursement_cents`.

Approving a rental moves it `PENDING → APPROVED`, but only when the parent claim has a `VERIFIED` coverage verification and the policy actually carries a `RENTAL` coverage, and only when the rental's `reimbursement_cents` is greater than zero. Approval creates a `RENTAL` disbursement in `APPROVED` status whose `amount_cents` is the positive `reimbursement_cents`, then recomputes the parent claim's `total_disbursed_cents`. Alternatively a rental is rejected, moving `PENDING → REJECTED`, precisely when its `reimbursement_cents` is zero or the policy carries no `RENTAL` coverage. Both `APPROVED` and `REJECTED` are terminal for a rental.

### 3.8. Claim Parties and Comparative Fault

A claim accumulates the people and entities involved in the loss. A `ClaimsAdjuster` or `ClaimsSupervisor` adds a claim party naming its claim through `claim_id`, with a `party_role` of `INSURED` or `THIRD_PARTY`, a `display_name`, an optional `fault_pct` between 0 and 100 inclusive (defaulting to 0) representing that party's assigned share of fault, and — for a third party only — an `at_fault_carrier_name` identifying the at-fault party's insurer, which becomes the subrogation target. At most one party with `party_role` `INSURED` may exist per claim; a second insured party is rejected with `ERR_DUPLICATE_INSURED_PARTY`.

### 3.9. Settlement and the Ledger

Settling a claim releases the first-party payout and is reserved for a `ClaimsSupervisor`. A claim may be settled from either disposition outcome — `REPAIR_APPROVED → SETTLED` or `TOTAL_LOSS → SETTLED` — and the rules are identical in both. The settle request carries `expected_claim_version` and is subject to the same concurrency refusal with `ERR_STALE_CLAIM_VERSION`; because the disposition decision already advanced the version, a settle carrying a pre-disposition version is stale. Settlement additionally requires that the claim's `settlement_cents` is strictly greater than zero, so that no zero-value disbursement is ever emitted; a settle attempt against a zero settlement is rejected with `ERR_NO_SETTLEMENT_AMOUNT`. On success the system creates a `SETTLEMENT` disbursement in `APPROVED` status whose `amount_cents` equals the positive `settlement_cents`, recomputes the claim's `total_disbursed_cents` from the ledger, and increments the claim's `version` by one.

Disbursements are never created directly by a client; they are emitted by the settle, rental-approval, and subrogation-resolution cascades. Each disbursement records its claim through `claim_id`, a `disbursement_type` of `SETTLEMENT`, `RENTAL`, or `SUBROGATION_RECOVERY`, the signed `amount_cents`, and a `source_entity_id` equal to the originating claim's id (pinning the ledger source). A disbursement is born `APPROVED` and the only further move available is voiding it. A `ClaimsSupervisor` may void an `APPROVED` disbursement as a compensating action, moving it `APPROVED → VOIDED`; this drops that disbursement's `amount_cents` out of the approved sum and, as a second hop, recomputes the parent claim's `total_disbursed_cents`, restoring it to the value it held before the disbursement was created.

A settled claim is closed by a `ClaimsSupervisor`, moving it `SETTLED → CLOSED`, which is the claim's only terminal state. Closing is permitted only when all recovery work is wrapped up: no subrogation case for the claim may be in `OPEN`, `DEMAND_SENT`, or `NEGOTIATING` status, and no rental reimbursement for the claim may be in `PENDING` status. The claim's net cash position can be read at any time through the computed ledger view, which returns `net_paid_cents` (the net approved-disbursement sum) and a `disbursement_count`.

### 3.10. Subrogation: Pursuing the Third Party

After a claim is settled, a `SubrogationSpecialist` may pursue recovery from the at-fault third party's carrier. Opening a subrogation case names its settled claim through `claim_id`, names the `target_party_id` of the third party whose carrier is pursued, and states a gross `demand_cents` before any fault reduction. A new case begins in `OPEN` status with `recovered_cents` of 0, and the system immediately computes its `recoverable_cents`.

The recoverable amount applies the insured's own comparative negligence to the demand. Let the insured fault be the claim's `insured_fault_pct`. Under the `PURE` rule the recovery is always the `demand_cents` multiplied by the quantity (100 minus the insured fault) divided by 100, rounded half-up to whole cents — the recovery is reduced by the fault percentage but never zeroed by a bar. Under the `MODIFIED_50` rule the recovery is zero when the insured fault is at or above 50, and otherwise the same reduced figure; so at exactly 50 percent fault the recovery is zero. Under the `MODIFIED_51` rule the recovery is zero only when the insured fault is at or above 51, and otherwise the same reduced figure; so at exactly 50 percent fault the insured still recovers half the demand. In every rule the percentage multiply is performed first and the result is rounded half-up to whole cents exactly once at the end.

A specialist sends the demand, moving the case `OPEN → DEMAND_SENT`; this requires that the parent claim is `SETTLED` and that `recoverable_cents` is greater than zero — a fully barred recovery cannot be demanded and the attempt is rejected with `ERR_NO_RECOVERABLE_AMOUNT`. Sending the demand recomputes `recoverable_cents`. The case may then move `DEMAND_SENT → NEGOTIATING`. From negotiation, the parties may bounce back to a revised demand: the specialist re-sends with a new `demand_cents`, moving `NEGOTIATING → DEMAND_SENT` and recomputing `recoverable_cents` against the revised demand. This counter-offer loop may repeat any number of times.

Resolution settles the case. A specialist resolves with a `recovered_cents` amount. When `recovered_cents` is greater than zero the case moves to `RESOLVED` (reachable from `NEGOTIATING`); when `recovered_cents` is zero the case moves to `CLOSED_NO_RECOVERY` (reachable from either `DEMAND_SENT` or `NEGOTIATING`). On resolution the recovered amount must satisfy zero at or below `recovered_cents` at or below `recoverable_cents`; a `recovered_cents` above the recoverable amount or below zero is rejected with `ERR_RECOVERY_EXCEEDS_DEMAND`. A successful recovery cascades in three hops: first the case's `status` becomes `RESOLVED` and its `recovered_cents` is stored; second, as a consequence, a `SUBROGATION_RECOVERY` disbursement is created in `APPROVED` status with an `amount_cents` of negative `recovered_cents` (an inbound credit); third, as a consequence of that disbursement creation, the parent claim's `total_disbursed_cents` is recomputed from the ledger. `RESOLVED` and `CLOSED_NO_RECOVERY` are both terminal for a subrogation case.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch a resource or drive a state transition on an existing resource return `200 OK`. Request and response payloads are not tabulated here — reconstruct each operation's inputs, computations, and side effects from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/policies` | Create a policy | ClaimsSupervisor |
| GET | `/policies/{id}` | Fetch a policy | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster, SubrogationSpecialist |
| POST | `/policies/{id}/lapse` | Mark a policy lapsed | ClaimsSupervisor |
| POST | `/policies/{id}/coverages` | Add a coverage line to a policy | ClaimsSupervisor |
| GET | `/policies/{id}/coverages` | List coverages for a policy | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster, SubrogationSpecialist |
| POST | `/adjusters` | Create an adjuster | ClaimsSupervisor |
| GET | `/adjusters/{id}` | Fetch an adjuster | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster |
| POST | `/claims` | File a first notice of loss | ClaimsAdjuster, ClaimsSupervisor |
| GET | `/claims/{id}` | Fetch a claim | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster, SubrogationSpecialist |
| GET | `/claims` | List claims (filter by policy_id, assigned_adjuster_id, status) | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster, SubrogationSpecialist |
| POST | `/claims/{id}/verify-coverage` | Run coverage verification | ClaimsAdjuster |
| POST | `/claims/{id}/assign-adjuster` | Assign an adjuster to a verified claim | ClaimsSupervisor |
| POST | `/claims/{id}/decide-disposition` | Decide repair or total-loss disposition | ClaimsAdjuster, TotalLossAdjuster |
| POST | `/claims/{id}/settle` | Settle an approved claim | ClaimsSupervisor |
| POST | `/claims/{id}/close` | Close a settled claim | ClaimsSupervisor |
| POST | `/claims/{id}/reopen` | Reopen a coverage-denied claim | ClaimsSupervisor |
| GET | `/claims/{id}/ledger` | Net cash ledger over the claim's approved disbursements | ClaimsSupervisor, ClaimsAdjuster, SubrogationSpecialist |
| GET | `/claims/{id}/coverage-verifications` | List coverage verifications for a claim | ClaimsSupervisor, ClaimsAdjuster |
| GET | `/claims/{id}/parties` | List parties for a claim | ClaimsSupervisor, ClaimsAdjuster, SubrogationSpecialist |
| GET | `/claims/{id}/disbursements` | List disbursements for a claim | ClaimsSupervisor, ClaimsAdjuster, SubrogationSpecialist |
| POST | `/claim-parties` | Add a party to a claim | ClaimsAdjuster, ClaimsSupervisor |
| POST | `/repair-estimates` | Create a draft repair estimate | ClaimsAdjuster |
| GET | `/repair-estimates/{id}` | Fetch a repair estimate | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster |
| GET | `/repair-estimates` | List repair estimates (filter by claim_id, authored_by_adjuster_id, status) | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster |
| POST | `/repair-estimates/{id}/submit` | Submit a draft estimate | ClaimsAdjuster |
| POST | `/total-loss-evaluations` | Author a total-loss evaluation | TotalLossAdjuster |
| GET | `/total-loss-evaluations/{id}` | Fetch a total-loss evaluation | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster |
| GET | `/total-loss-evaluations` | List total-loss evaluations (filter by claim_id, evaluated_by_adjuster_id) | ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster |
| POST | `/rental-reimbursements` | Compute a rental reimbursement | ClaimsAdjuster |
| GET | `/rental-reimbursements/{id}` | Fetch a rental reimbursement | ClaimsSupervisor, ClaimsAdjuster |
| GET | `/rental-reimbursements` | List rental reimbursements (filter by claim_id, status) | ClaimsSupervisor, ClaimsAdjuster |
| POST | `/rental-reimbursements/{id}/approve` | Approve a rental reimbursement | ClaimsAdjuster |
| POST | `/rental-reimbursements/{id}/reject` | Reject a rental reimbursement | ClaimsAdjuster |
| POST | `/subrogation-cases` | Open a subrogation case | SubrogationSpecialist |
| GET | `/subrogation-cases/{id}` | Fetch a subrogation case | ClaimsSupervisor, SubrogationSpecialist |
| GET | `/subrogation-cases` | List subrogation cases (filter by claim_id, target_party_id, status) | ClaimsSupervisor, SubrogationSpecialist |
| POST | `/subrogation-cases/{id}/send-demand` | Send or re-send a revised demand | SubrogationSpecialist |
| POST | `/subrogation-cases/{id}/begin-negotiation` | Move a sent demand into negotiation | SubrogationSpecialist |
| POST | `/subrogation-cases/{id}/resolve` | Resolve a subrogation case | SubrogationSpecialist |
| GET | `/disbursements/{id}` | Fetch a disbursement | ClaimsSupervisor, ClaimsAdjuster, SubrogationSpecialist |
| POST | `/disbursements/{id}/void` | Void an approved disbursement | ClaimsSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_SENIOR_TIER_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_COVERAGE` | 409 Conflict |
| `ERR_DUPLICATE_INSURED_PARTY` | 409 Conflict |
| `ERR_NO_SUBMITTED_ESTIMATE` | 409 Conflict |
| `ERR_NOT_A_TOTAL_LOSS` | 409 Conflict |
| `ERR_NO_RECOVERABLE_AMOUNT` | 409 Conflict |
| `ERR_INVALID_RENTAL_INTERVAL` | 422 Unprocessable Entity |
| `ERR_RECOVERY_EXCEEDS_DEMAND` | 409 Conflict |
| `ERR_NO_SETTLEMENT_AMOUNT` | 409 Conflict |
| `ERR_RENTAL_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_POLICY_PERIOD_OVERLAP` | 409 Conflict |
