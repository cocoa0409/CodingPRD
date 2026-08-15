# Multifamily Acquisition Due Diligence API — Product Requirements Document

## 1. Introduction

Buying a multifamily asset is an exercise in reconciling what the seller says with what the paper trail proves. The rent roll inflates collections with phantom tenants, lease files disagree with the marketing schedule, deposit ledgers omit statutory interest, and a stack of vendor contracts quietly auto-renews the day after closing while the tax assessor waits to revalue the whole parcel. Diligence teams currently chase these threads through spreadsheets and email, and the cost of a missed item surfaces months later as an unrecoverable post-closing loss.

This document specifies the Multifamily Acquisition Due Diligence API, a system that runs an acquisition from project intake through escrow settlement as a single auditable ledger. The API coordinates eight diligence workstreams — lease-file audit against the seller rent roll, concession verification, unit-walk inspections with deferred-maintenance quantification, utility and expense normalization, tax-reassessment projection, security-deposit reconciliation and transfer, employee retention and severance planning, service-contract assumption or cancellation, insurance loss-run review, and the generation of closing prorations together with post-closing true-up adjustments. Every figure that reaches the closing statement is derived from a verified upstream record, and every approval that moves the deal forward respects segregation of duties between the analyst who prepared the work and the manager who signs off on it.

## 2. Global Specifications & System-Wide Principles

This section states the rules that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting operator and `X-User-Role` names their capacity. The declared role catalog is `PlatformAdmin`, `AcquisitionsAnalyst`, `UnderwritingManager`, `PropertyOperationsLead`, `HRPartner`, `VendorManager`, and `EscrowOfficer`, spelled exactly as written here. A request missing either header, or presenting a role outside the declared catalog, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Every read endpoint is available to all seven roles; write authorization is enumerated per endpoint in §4.

All seven roles share the same identity model: for each of `PlatformAdmin`, `AcquisitionsAnalyst`, `UnderwritingManager`, `PropertyOperationsLead`, `HRPartner`, `VendorManager`, and `EscrowOfficer`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution — for example as `completed_by_user_id` on a walk inspection, `proposed_by_user_id` and `approved_by_user_id` on an employee decision, or `created_by_user_id`, `reviewed_by_user_id`, and `approved_by_user_id` on a proration statement — and segregation-of-duties checks compare those stored identifiers against the caller's `X-User-ID`. The server never compares `X-User-ID` to any entity's `id`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending, with ties broken by `id` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Validation Order and Nested Resource Retrieval

The server applies a fixed validation order to every request, from cheapest and most general to most specific: first authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every identifier referenced by the request (the 404 family), then request shape (`ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`, `ERR_INVALID_DATE_RANGE`), then state-machine legality (the 409 state family including `ERR_INVALID_STATE_TRANSITION`, the acquisition phase gates, `ERR_STATEMENT_NOT_REVIEWED`, `ERR_STATEMENT_NOT_SETTLABLE`, `ERR_LEASE_NOT_AUDITED`, and `ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE`), then optimistic-concurrency staleness (`ERR_STALE_VERSION`), then referential and segregation-of-duties checks (`ERR_SOD_VIOLATION`, `ERR_SUPERSEDE_TARGET_NOT_CURRENT`, `ERR_RENT_ROLL_ENTRY_MISSING`), then compliance gates (`ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE`, `ERR_ACQUISITION_BLOCKED`, `ERR_UNRESOLVED_AUDIT_ITEMS`), then uniqueness and readiness constraints (the duplicate/existence family plus `ERR_INSPECTION_NOT_COMPLETED` and `ERR_FINDINGS_REQUIRED`), then temporal rules (the notice-window, overlap, and clock-ordering family), and finally fiscal rechecks (`ERR_STATEMENT_DRIFT`, `ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE`, `ERR_DEPOSIT_VARIANCE_UNRESOLVED`). Because earlier checks run before later ones, a request that would fail at two levels surfaces the earlier error — for example, an approve issued by the statement's own creator reports `ERR_SOD_VIOLATION` even if the statement's generated lines would also drift. One carve-out applies to action endpoints that transition an existing resource: the target resource's own state-machine legality is checked immediately after its existence and before the request body's field-level validation, so a transition attempted from the wrong source state reports its 409 even when the body is also malformed or incomplete.

Existence is validated left-to-right across the request: identifiers appearing earlier in the path are checked before later ones, and path identifiers are checked before foreign keys supplied in the body (`unit_id`, `lease_file_id`, `inspection_id`, `acquisition_id`, `supersedes_lease_id`). The 404 family is one error per entity type: `ERR_ACQUISITION_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_LEASE_FILE_NOT_FOUND`, `ERR_CONCESSION_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_UTILITY_RECORD_NOT_FOUND`, `ERR_TAX_PROJECTION_NOT_FOUND`, `ERR_DEPOSIT_NOT_FOUND`, `ERR_EMPLOYEE_DECISION_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_INSURANCE_POLICY_NOT_FOUND`, `ERR_PRORATION_STATEMENT_NOT_FOUND`, and `ERR_ADJUSTMENT_NOT_FOUND`.

### 2.5. Common Resource Properties, Money, and Dates

Most resources carry four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource — including status changes a cascade applies to the resource itself, such as supersession, closing transfers, termination rescission, contract auto-renewal, and findings verified by QA acceptance. Purely derived recomputation is not a mutation for this purpose: when child activity recomputes an acquisition's rollup totals or `readiness_posture`, or a unit's readiness flags, the new values are written in place and the owning resource's `version` and `updated_at` advance only when its own `status` also changes — an acquisition whose rollups or posture shift without a phase change keeps its `version`, and a unit whose flags flip while its compound status stays the same keeps its `version`. Two resource kinds are deliberately leaner: a rent roll entry and a proration line carry only `id` and `created_at`; they have no `updated_at` and no `version`, because entries on the seller's rent roll and lines inside a statement are never mutated in place — corrections flow through the owning lease or statement instead.

All monetary amounts are integer cents end to end; no field ever carries fractional cents. Wherever a multiplication or division in a calculation produces a fraction, the result is rounded half up to integer cents at the step where it appears, in the order the steps are written in §3. Dates and datetimes are ISO 8601 UTC; day-count arithmetic counts calendar days between the date portions of two timestamps.

### 2.6. Optimistic Concurrency Control

Three write endpoints require the caller to attest which version of a parent record their work is based on, and the attestation field is non-optional on exactly those three endpoints. Creating a tax reassessment projection must carry `expected_acquisition_version` equal to the acquisition's current `version`; the creation supersedes the currently approved projection, so a create issued with a stale version would silently retire a projection the caller never saw, and it is rejected with `ERR_STALE_VERSION` (HTTP 412). Generating a proration statement likewise must carry `expected_acquisition_version` matching the acquisition's current `version`, because generation supersedes the approved statement of the preceding type and mutates acquisition fields; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Appending a manual line to a proration statement must carry `expected_statement_version` equal to the statement's current `version`, since the append recomputes the statement's totals; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field — all other writes are serialized purely by state-machine legality.

### 2.7. The Logical Clock

The server runs on a logical clock rather than wall-clock time. At startup, before any operator intervention, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant through the test-driving clock capability; the response reports the new `current_utc`. The set accepts any valid instant — no monotonicity check is enforced, so a `to_iso8601` earlier than the current reading is accepted as written. Advancing the clock runs the service-contract auto-renew sweep described in §3.7. Everywhere the specification says "the logical clock" — notice windows, effective dates, true-up windows, the trailing expense window — the comparison is against this clock, not the request wall time.

### 2.8. Segregation of Duties

Four workflows separate the person who performs work from the person who accepts it. A proration statement's reviewer must differ from its `created_by_user_id`, and its approver must differ from both `created_by_user_id` and `reviewed_by_user_id`. An employee decision's approver must differ from its `proposed_by_user_id`. A walk inspection's QA caller — accept or reject — must differ from the `completed_by_user_id` who performed the walk. Each breach is rejected with `ERR_SOD_VIOLATION` (HTTP 409). The system compares opaque `X-User-ID` strings per §2.1; no other identity model applies.

## 3. Business Logic & Workflows

### 3.1. Project Intake and the Acquisition Lifecycle

An `AcquisitionsAnalyst` opens a diligence project by registering an acquisition with its `property_name`, `address`, the `agreed_purchase_price_cents` under contract, the `earnest_money_cents` posted, the scheduled `closing_date`, the `diligence_deadline`, the jurisdiction's `assessment_ratio` and `millage_rate`, and the `prior_year_tax_cents` most recently billed for a full year. Three settings carry defaults the analyst may override at intake: `true_up_window_days` defaults to 90 days after closing during which post-closing adjustments may be asserted; `maintenance_estimate_basis` defaults to `INSPECTOR_BASIS` (the alternative being `SELLER_BASIS`) and selects which cost estimate feeds the deferred-maintenance rollup; and `interest_accrual_method` defaults to `DAILY_ACCRUAL` (the alternative being `SIMPLE_ANNUAL`) and governs deposit interest. A new acquisition opens in `DRAFT` status with `readiness_posture` `ON_TRACK` and every computed money field at zero: `deferred_maintenance_total_cents`, `rent_roll_variance_cents`, `deposit_variance_cents`, `payroll_accrual_cents`, and `net_proration_cents` all start at 0, and `closing_executed_at` stays null until closing executes.

While the acquisition is `DRAFT` or `IN_DILIGENCE`, an `UnderwritingManager` may amend `closing_date`, `maintenance_estimate_basis`, or `interest_accrual_method`. Switching the basis re-derives every `VERIFIED` finding's `verified_cost_cents` and the deferred-maintenance rollup from the other estimate column; findings in other statuses keep their stored values until they re-enter `VERIFIED`. Deposit interest is never cached against stale parameters: it is always computed at reconcile or dispute-resolution time from the acquisition's current `closing_date` and `interest_accrual_method`, so amending either one needs no eager recompute. Each accepted amendment call bumps the acquisition's `version` by one, even when the payload changes no field.

The deal advances through a posture-driven phase machine. Kickoff by an `UnderwritingManager` moves `DRAFT` to `IN_DILIGENCE` and recomputes `readiness_posture`. Completing diligence moves `IN_DILIGENCE` to `DILIGENCE_COMPLETE` and enforces four gates: the posture must not be `BLOCKED` (else `ERR_ACQUISITION_BLOCKED`); no lease file belonging to a non-`EXCLUDED` unit may remain `UPLOADED` or `DISCREPANCY_FLAGGED`; no deposit ledger entry may remain `RECORDED` or `DISPUTED`; and every non-`EXCLUDED` unit must have reached `VERIFIED` — the latter three violations all surface as `ERR_UNRESOLVED_AUDIT_ITEMS`. Advancing to `PRE_CLOSING` requires that a `DRAFT_CLOSING` proration statement already exist in `APPROVED` status (else `ERR_NO_APPROVED_DRAFT_STATEMENT`). Executing closing moves `PRE_CLOSING` to `CLOSED` and is the heaviest gate in the system, checked in the order given: a `FINAL_CLOSING` statement in `APPROVED` status must exist (else `ERR_NO_APPROVED_FINAL_STATEMENT`); every deposit ledger entry must be `ESCROW_QUEUED` or `TRANSFERRED` (else `ERR_DEPOSITS_NOT_QUEUED`); no employee decision may remain `PROPOSED` (else `ERR_OPEN_DECISIONS_REMAIN`); and no service contract may remain `IDENTIFIED` or `UNDER_REVIEW` (else `ERR_OPEN_SERVICE_CONTRACTS_REMAIN`).

A successful closing stamps `closing_executed_at` from the logical clock and fires a cascade in a fixed order. First, every deposit entry in `ESCROW_QUEUED` moves to `TRANSFERRED`. Second, because those entries moved, the `DEPOSIT_TRANSFER` generated line on the `FINAL_CLOSING` statement is regenerated as the sum of `verified_amount_cents` plus `accrued_interest_cents` over all `TRANSFERRED` entries. Third, because that line changed, the statement's `total_buyer_credits_cents`, `total_seller_credits_cents`, and `net_amount_cents` recompute, and the acquisition's `net_proration_cents` re-derives from the statement. In parallel with the deposit chain, every service contract in `ASSUMED` moves to `TRANSFERRED` and every insurance policy in `ASSUMED` moves to `TRANSFERRED`.

Settlement moves `CLOSED` to `SETTLED` and belongs to the `EscrowOfficer`. It requires four conditions: the logical clock must be strictly later than `closing_executed_at` plus `true_up_window_days` days (settling earlier is `ERR_TRUE_UP_WINDOW_OPEN`); the `FINAL_CLOSING` statement must be `SETTLED` (else `ERR_FINAL_STATEMENT_NOT_SETTLED`); every `POST_CLOSING_TRUEUP` statement that exists must be `SETTLED` (else `ERR_TRUEUP_STATEMENT_NOT_SETTLED`); and no post-closing adjustment may sit in any non-terminal status among `ASSERTED`, `EVIDENCED`, `ACCEPTED`, `DISPUTED`, or `RESOLVED` (else `ERR_OPEN_ADJUSTMENTS_REMAIN`).

Termination is available from `DRAFT`, `IN_DILIGENCE`, `DILIGENCE_COMPLETE`, or `PRE_CLOSING` and lands in the terminal `TERMINATED` state. From any of the four phases, every employee decision in `APPROVED` or `NOTIFIED` is rescinded to `RESCINDED`, removing its contribution to `payroll_accrual_cents`. Terminating from `PRE_CLOSING` additionally unwinds the deal's vendor posture: every service contract in `ASSUMED` or `NOTICE_SENT` is force-moved to `CANCELLED_EFFECTIVE`. `SETTLED` and `TERMINATED` are terminal; a terminated or settled acquisition rejects every further mutation of the acquisition itself — amendment and every lifecycle transition — and the creation of any new child resource under it, all with `ERR_INVALID_STATE_TRANSITION`. State transitions on child records that already exist are not blocked by the acquisition's terminal status.

### 3.2. Units and the Readiness Rollup

Units are registered against an acquisition by an `AcquisitionsAnalyst` supplying `unit_number`, `floor_plan`, `sqft`, and `market_rent_cents` along with the owning `acquisition_id`. The `unit_number` must be unique within its acquisition; a duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER`. A unit opens in `REGISTERED` status with all three readiness flags false: `lease_audited`, `walk_accepted`, and `deposit_reconciled`.

Each flag is a derived summary of one workstream. `lease_audited` is true when the unit's current lease file — the one whose status is not `SUPERSEDED` — is in `AUDITED`, `RESOLVED`, or `WAIVED`. `walk_accepted` is true when the unit's latest non-cancelled walk inspection — latest by `created_at`, ties broken by `id` — stands at `QA_ACCEPTED`. `deposit_reconciled` is true when at least one deposit ledger entry exists for the unit's current lease and that entry is `RECONCILED`, `ESCROW_QUEUED`, or `TRANSFERRED`.

The unit's `status` is a system-driven compound rollup, never set directly. The first time any one of the three flags turns true, the unit moves from `REGISTERED` to `CLEARING`. When all three flags are simultaneously true, the unit moves from `CLEARING` to `VERIFIED` and the acquisition's `readiness_posture` is recomputed. If any flag later flips back to false — for example because a lease is re-flagged — a `VERIFIED` unit demotes to `CLEARING` and posture is again recomputed. A `CLEARING` unit whose flags all fall back to false stays `CLEARING`; there is no regression to `REGISTERED`. An `AcquisitionsAnalyst` may exclude a unit in `REGISTERED` or `CLEARING`; exclusion lands in the terminal `EXCLUDED` state and removes the unit from audit scope, from the rent proration input set, and from posture derivation, so the unit's leases and findings no longer count anywhere. There is no path out of `EXCLUDED`.

### 3.3. Lease-File Audit Against the Seller Rent Roll

The seller's claimed income arrives as one rent roll entry per unit, recorded by an `AcquisitionsAnalyst` with `reported_resident_name`, `reported_rent_cents`, `reported_concession_cents`, `reported_deposit_cents`, and `move_in_date`. At most one rent roll entry may exist per unit; a second attempt is rejected with `ERR_RENT_ROLL_ENTRY_EXISTS`. A new entry's `verification_status` is `UNVERIFIED` and changes only as a side effect of lease audit activity — no endpoint writes it directly.

Against each unit the analyst uploads lease files carrying `resident_name`, `lease_start_date`, `lease_end_date`, the `contract_rent_cents` the lease document actually specifies, the `term_months`, and the `deposit_amount_cents` the lease requires. A lease opens as `UPLOADED` with `audit_result` `PENDING` and `variance_cents` null. A unit has at most one current lease; uploading a second lease for a unit that already has a current one is rejected with `ERR_ACTIVE_LEASE_EXISTS` unless the payload supplies `supersedes_lease_id` naming that current lease, in which case the named lease moves to `SUPERSEDED` as the new one is accepted. A `supersedes_lease_id` that names anything other than the unit's current non-`SUPERSEDED` lease is rejected with `ERR_SUPERSEDE_TARGET_NOT_CURRENT`. Supersession may strike the current lease whatever its status — `UPLOADED`, `AUDITED`, `DISCREPANCY_FLAGGED`, `RESOLVED`, or `WAIVED`; in every supersession the unit's `lease_audited` flag is recomputed, and superseding a `DISCREPANCY_FLAGGED` lease additionally recomputes the acquisition's `rent_roll_variance_cents` and `readiness_posture` because the flagged row leaves the open-exposure set. Lease files for a unit can be listed either through the unit's collection or by filtering the global list by `unit_id`, by `status`, or by `supersedes_lease_id` to find the leases a given lease retired.

Auditing an `UPLOADED` lease compares it to the unit's rent roll entry. The audit requires that an entry exist for the unit, else `ERR_RENT_ROLL_ENTRY_MISSING` (HTTP 422). The auditor computes `variance_cents` as the entry's `reported_rent_cents` minus the lease's `contract_rent_cents`. When the absolute variance is less than 500 cents — the rent-variance materiality threshold — the lease lands `AUDITED`, the entry's `verification_status` becomes `VERIFIED`, and `audit_result` records `MATCH`. When the absolute variance is at least 500 cents, the lease instead lands `DISCREPANCY_FLAGGED`, the entry becomes `MISMATCHED`, and `audit_result` records `OVERSTATED` when the reported rent exceeds the contract rent or `UNDERSTATED` when it falls short. Either way, the unit's `lease_audited` recomputes (possibly driving the unit toward `CLEARING` or `VERIFIED`), and the acquisition's `rent_roll_variance_cents` recomputes; a flagging additionally recomputes `readiness_posture`, which stands `BLOCKED` while any flagged lease on a non-excluded unit remains open.

The acquisition-level `rent_roll_variance_cents` is the sum of each flagged lease's `variance_cents` — reported minus contract — over lease files in `DISCREPANCY_FLAGGED` status whose unit is not `EXCLUDED`. Only open exposure counts: `AUDITED`, `RESOLVED`, and `WAIVED` leases contribute zero.

Discrepancies close three ways. Resolution by an `AcquisitionsAnalyst` moves `DISCREPANCY_FLAGGED` to `RESOLVED`; the request carries a `resolution_note` and may carry `corrected_contract_rent_cents`, which when supplied replaces `contract_rent_cents` and triggers recomputation of both `variance_cents` and `net_effective_rent_cents`. Resolution sets the rent roll entry back to `VERIFIED`, recomputes `lease_audited` (which may promote the unit from `CLEARING` to `VERIFIED`), and recomputes the acquisition rollup and posture. Waiver by an `UnderwritingManager` moves `DISCREPANCY_FLAGGED` to the terminal `WAIVED` state on the strength of a `waiver_note`; the lease records `waived_variance_cents` equal to the variance the buyer accepted, leaves the open-variance sum (so the acquisition rollup recomputes downward), does not touch the rent roll entry — it remains `MISMATCHED` — and recomputes `lease_audited` and posture. The third path is the revision loop: an analyst may re-flag a lease in `AUDITED` or `RESOLVED` by supplying a `reason`, sending it back to `DISCREPANCY_FLAGGED`. Re-flagging first recomputes `variance_cents` from the unit's rent roll entry against the lease's current `contract_rent_cents`, then cascades in order — the rent roll entry returns to `MISMATCHED`; because the entry mismatched, the unit's `lease_audited` flips false and a `VERIFIED` unit demotes to `CLEARING`; because the unit demoted, the acquisition's `readiness_posture` recomputes.

Concessions attach to a lease with a `concession_type` of `RECURRING_MONTHLY`, `ONE_TIME_CREDIT`, or `FREE_MONTH_AMORTIZED`; a `value_cents` whose meaning is the monthly credit for the recurring type and the total credit for the other two; and a coverage window from `coverage_start_date` through `coverage_end_date` that is a closed interval — both endpoints are included days. Two concessions on the same lease may not share even one calendar day of coverage; any overlap between a new concession and an existing `PENDING` or `VERIFIED` concession on the same lease is rejected with `ERR_CONCESSION_OVERLAP`. A concession's state is carried in its `verification_status` field and opens `PENDING`, and a pending concession keeps the acquisition's posture at least `AT_RISK`. Verification by an analyst supplies the accepted `verified_value_cents` and moves the concession to `VERIFIED`; rejection with an optional `reason` moves it to `REJECTED`. Both actions recompute the lease's `net_effective_rent_cents` and the acquisition's posture.

`net_effective_rent_cents` is the lease's concession-adjusted monthly rent: take `contract_rent_cents` times `term_months`, subtract the sum of `verified_value_cents` over the lease's `VERIFIED` concessions only (pending and rejected concessions are excluded), divide by `term_months`, and round half up to integer cents at that final division.

### 3.4. Unit Walks and Deferred Maintenance Quantification

A `PropertyOperationsLead` schedules a unit walk by naming the `unit_id`, the `inspector_ref` whose calendar the walk books, and a half-open window from `walk_start` (inclusive) to `walk_end` (exclusive). The window must be non-empty: a `walk_end` not strictly after `walk_start` is rejected with `ERR_INVALID_DATE_RANGE`. The window must not overlap any other inspection in `SCHEDULED` or `COMPLETED` status booked under the same `inspector_ref` — a `QA_REJECTED` inspection awaiting reschedule does not block the inspector's calendar — and because the interval is half-open, two walks that merely touch, one's `walk_end` equaling the other's `walk_start`, do not overlap and are allowed; a genuine overlap is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. The inspection opens `SCHEDULED` with `reschedule_count` at zero.

Completing the walk records a `condition_rating` from 1 to 5 — a rating outside that range is rejected with `ERR_INVALID_REQUEST` — and the completer's `no_findings_declared` declaration that zero deficiencies exist, and stamps `completed_by_user_id` with the caller's `X-User-ID`. Quality assurance then judges the walk. QA acceptance requires that the caller differ from `completed_by_user_id` (else `ERR_SOD_VIOLATION`) and, when `no_findings_declared` is false, that at least one deficiency finding exist for the inspection (else `ERR_FINDINGS_REQUIRED`). Acceptance lands the inspection in the terminal `QA_ACCEPTED` state and cascades in order: every finding of this inspection still `OPEN` moves to `VERIFIED`; because findings entered the rollup, the acquisition's `deferred_maintenance_total_cents` recomputes; because the rollup moved, `readiness_posture` recomputes and may cross the 3% or 5% thresholds described in §3.9; and the unit's `walk_accepted` flag recomputes, possibly promoting the unit. QA rejection likewise requires a caller different from the completer and carries a mandatory `reason`, moves the inspection to `QA_REJECTED`, and forces the acquisition's posture to at least `AT_RISK` while any rejected inspection exists. Rescheduling a rejected walk supplies a fresh `walk_start` and `walk_end` — the inspector-overlap check applies again — returns the inspection to `SCHEDULED`, increments `reschedule_count` by one, clears `condition_rating`, `no_findings_declared`, and `completed_by_user_id`, and recomputes posture.

Deficiency findings are recorded against a `COMPLETED` inspection — recording against an inspection in any other state is rejected with `ERR_INSPECTION_NOT_COMPLETED` — with a `category` of `LIFE_SAFETY`, `MAJOR_SYSTEMS`, `CODE_COMPLIANCE`, or `COSMETIC`, a `severity` from 1 to 5 (a severity outside that range is rejected with `ERR_INVALID_REQUEST`), the `seller_estimate_cents`, and the `inspector_estimate_cents`. A finding opens `OPEN`. The operations lead may verify an `OPEN` finding directly, dispute an already `VERIFIED` one (an `UnderwritingManager` action carrying a `reason`), re-verify a `DISPUTED` one, or exclude an `OPEN` or `DISPUTED` one into the terminal `EXCLUDED` state with a mandatory `reason`.

Each finding's `verified_cost_cents` is computed when it enters or re-enters `VERIFIED`. The base is `inspector_estimate_cents` when the acquisition's `maintenance_estimate_basis` is `INSPECTOR_BASIS` and `seller_estimate_cents` when it is `SELLER_BASIS`. The base is multiplied by a severity multiplier — 1.00 for severity 1 or 2, 1.15 for severity 3, 1.25 for severity 4, and 1.40 for severity 5 — and that product is rounded half up to integer cents before the flat category loading is added: plus 15000 cents for `LIFE_SAFETY`, plus 5000 cents for `CODE_COMPLIANCE`, and nothing for `MAJOR_SYSTEMS` or `COSMETIC`. Verification and re-verification recompute this cost and the acquisition rollup; disputing a verified finding removes it from the rollup and recomputes; changing the acquisition's basis re-derives every `VERIFIED` finding's `verified_cost_cents` and the rollup in one pass.

The acquisition's `deferred_maintenance_total_cents` is the sum of `verified_cost_cents` over findings in `VERIFIED` status whose unit is not `EXCLUDED`. `OPEN`, `DISPUTED`, and `EXCLUDED` findings contribute nothing.

### 3.5. Utility and Expense Normalization

Expense history is captured as one record per month per category, created by an analyst with the `acquisition_id`, the `period_month` in `YYYY-MM` form (carried as an opaque string — its shape is not validated at creation, and a malformed value simply never falls inside the trailing window), a `category` of `ELECTRIC`, `GAS`, `WATER_SEWER`, `TRASH`, or `OTHER`, the `amount_cents` recorded, and a `source` of `SELLER_T12`, `BILL_AUDIT`, or `ESTIMATE`. The triple of acquisition, `period_month`, and `category` is unique; a duplicate is rejected with `ERR_UTILITY_RECORD_EXISTS`. Records are filterable by `acquisition_id`, `category`, and `period_month`.

Normalization works over a trailing window: the twelve complete calendar months strictly before the logical clock's current month. Within the window, only rows whose source is `SELLER_T12` or `BILL_AUDIT` participate — `ESTIMATE` rows are excluded from averages, from sums, and from outlier math. An `ESTIMATE` row is therefore never itself subjected to the outlier test: its `is_outlier` is always false and its `normalized_amount_cents` always equals its own `amount_cents`. A row's category trailing average is the sum of `amount_cents` over the included rows of that category excluding the row under test, divided by their count, rounded half up to integer cents. The row's `is_outlier` flag is true when its `amount_cents` is strictly more than 1.20 times that average or strictly less than 0.80 times it — the comparisons are strict, so a row exactly twenty percent above or below the average is not an outlier. The row's `normalized_amount_cents` is its own `amount_cents` when not an outlier and the rounded category average when it is. Each record's stored `is_outlier` and `normalized_amount_cents` are computed once, at creation, against the trailing window as of the creating clock; the expense summary instead recomputes the outlier math fresh from live rows on every read.

The expense summary read returns the trailing-12 picture: `total_t12_raw_cents` and `total_t12_normalized_cents` across the window's included rows, an `outlier_count`, and a `by_category` breakdown holding one entry per category — always all five, in the canonical order `ELECTRIC`, `GAS`, `WATER_SEWER`, `TRASH`, `OTHER` — each entry carrying `category`, `raw_cents`, `normalized_cents`, `row_count`, and `outlier_count`. A category with no included rows in the window contributes zero.

### 3.6. Tax Reassessment Projection

Jurisdictions reassess on sale, so the acquisition models its future tax bill with a projection created under the acquisition — the create carries the OCC field `expected_acquisition_version` per §2.6 and takes a `method` of `PURCHASE_PRICE_ANCHORED` or `INCOME_APPROACH`. The income approach additionally requires a `cap_rate` and a `noi_t12_cents` giving trailing-twelve-month net operating income computed with prior-year taxes, which breaks the circularity between tax and NOI: the projected tax computed here must never feed back into the NOI. Creating a projection opens it in `DRAFT`, supersedes whichever projection of the same acquisition currently stands `APPROVED` (moving it to `SUPERSEDED`), and increments the acquisition's `version` by one. Projections list by `acquisition_id` and `status`.

Computing a `DRAFT` projection runs a pinned one-pass evaluation in a fixed order — value conclusion first, then assessed value, then projected tax — and lands the projection in `COMPUTED`. Under `PURCHASE_PRICE_ANCHORED` the `projected_value_cents` is simply the acquisition's `agreed_purchase_price_cents`. Under `INCOME_APPROACH` the `projected_value_cents` is `noi_t12_cents` divided by `cap_rate`, rounded half up to integer cents. The `projected_assessed_value_cents` is the `projected_value_cents` multiplied by the acquisition's `assessment_ratio`, rounded half up. The `projected_annual_tax_cents` is the `projected_assessed_value_cents` multiplied by the acquisition's `millage_rate` and divided by 1000 — millage being mills per dollar of assessed value — rounded half up. The `delta_vs_prior_cents` is the `projected_annual_tax_cents` minus the acquisition's `prior_year_tax_cents`, so a positive delta is new tax burden the buyer underwrites. The two methods produce different values and taxes for identical acquisition data.

An `UnderwritingManager` may approve a `COMPUTED` projection; approval supersedes any other projection of the same acquisition currently `APPROVED`. Revision returns a `COMPUTED` projection to `DRAFT` and clears its computed fields. A projection leaves `APPROVED` only by supersession — a new projection created under the same acquisition, or another projection approved — and when an approved projection is superseded, any proration statement referencing it drifts: its tax line no longer matches the currently approved projection and will fail the approve-time drift check described in §3.8 until regenerated.

### 3.7. Vendor Contracts and Insurance

A `VendorManager` registers each service contract with its `vendor_name`, a `service_type` of `ELEVATOR`, `LAUNDRY`, `LANDSCAPING`, `PEST_CONTROL`, `SECURITY`, or `OTHER`, the `monthly_cost_cents`, the current `term_end_date`, whether the contract `auto_renew`s absent timely notice, the `cancellation_notice_days` required before term end, the `cancellation_penalty_cents` payable on cancellation, and optionally the `prepaid_through_date` through which the seller has prepaid the service. The contract opens `IDENTIFIED` with its `decision_deadline` computed as `term_end_date` minus `cancellation_notice_days` calendar days — the last day on which notice may be sent.

Review moves the contract `IDENTIFIED` to `UNDER_REVIEW`. From review the vendor manager may assume the contract, landing it `ASSUMED` and entering it into the prepaid-expense proration input set whenever its `prepaid_through_date` falls after the acquisition's `closing_date`; may renew it into the terminal `RENEWED` state; or may send cancellation notice with a chosen `cancellation_effective_date`, landing it `NOTICE_SENT`. Notice requires the logical clock to be on or before the `decision_deadline` — the deadline day itself is still allowed, and a clock past the deadline is rejected with `ERR_NOTICE_WINDOW_MISSED` — and requires the acquisition to be in `IN_DILIGENCE`, `DILIGENCE_COMPLETE`, or `PRE_CLOSING` (else `ERR_INVALID_STATE_TRANSITION`). Once the logical clock reaches the recorded `cancellation_effective_date`, the contract may be marked cancelled into the terminal `CANCELLED_EFFECTIVE` state; marking earlier is rejected with `ERR_CANCELLATION_NOT_YET_EFFECTIVE`. Contracts that nobody touches are not inert: when the logical clock advances past the `decision_deadline` of an `IDENTIFIED` or `UNDER_REVIEW` contract whose `auto_renew` is true, the auto-renew sweep moves it to the terminal `AUTO_RENEWED` state. Assumed contracts transfer at closing per §3.1.

Insurance follows a parallel discipline under the `UnderwritingManager`. A policy is registered with its `policy_type` — `PROPERTY`, `GENERAL_LIABILITY`, `UMBRELLA`, `FLOOD`, or `OTHER` — the `carrier_name`, the `annual_premium_cents`, the `expiration_date`, the `prepaid_through_date`, the aggregate three-year `loss_run_total_cents`, and the `open_claims_count`. It opens `DOCUMENTED`. Reviewing the loss runs moves the policy to `LOSS_RUNS_REVIEWED` and computes two derived fields. The `loss_ratio` is the `loss_run_total_cents` divided by three times the `annual_premium_cents`; when `annual_premium_cents` is zero the ratio is defined as 0. The `risk_tier` is `LOW` when the ratio is below 0.40, `ELEVATED` when it is at least 0.40 and below 0.80, and `HIGH` when it is at least 0.80 — the comparison is exact decimal, so a ratio of precisely 0.80 is `HIGH`. Assuming a reviewed policy moves it to `ASSUMED` and enters it into the prepaid-expense proration input set; assuming a `HIGH`-tier policy requires the caller to pass `override_high_risk` as true, and is otherwise rejected with `ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE`. A policy in `DOCUMENTED` or `LOSS_RUNS_REVIEWED` may instead be excluded with an optional `reason`, landing in the terminal `EXCLUDED` state. Assumed policies transfer at closing.

### 3.8. Closing Prorations and Statement Settlement

Proration statements are the deal's accounting spine. An `UnderwritingManager` generates a statement against an acquisition — the generate carries the OCC field `expected_acquisition_version` per §2.6 — by naming a `statement_type` of `DRAFT_CLOSING`, `FINAL_CLOSING`, or `POST_CLOSING_TRUEUP` and a `day_count_method` of `ACTUAL_365` or `BANKERS_30_360`. Statement type is gated by acquisition phase: a `DRAFT_CLOSING` statement may be generated only while the acquisition is `DILIGENCE_COMPLETE` or `PRE_CLOSING`, a `FINAL_CLOSING` only while `PRE_CLOSING`, and a `POST_CLOSING_TRUEUP` only while `CLOSED`; any other pairing is rejected with `ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE`. Generation also requires an approved tax reassessment projection to already exist for the acquisition — the generated line set always includes the tax line — and is rejected with `ERR_TAX_PROJECTION_NOT_APPROVED` when none exists; this check runs after the phase gate and the `expected_acquisition_version` check. Generation computes the statement's generated lines from live data per the proration rules below, supersedes the approved statement of the preceding type — concretely, only a new `FINAL_CLOSING` supersedes anything, retiring the approved `DRAFT_CLOSING` to `SUPERSEDED`; generating a `DRAFT_CLOSING` or a `POST_CLOSING_TRUEUP` retires nothing, and an approved statement of the same type is never superseded — stamps `created_by_user_id` with the caller, opens the statement in `DRAFT`, and increments the acquisition's `version` by one.

Every statement carries `total_buyer_credits_cents` as the sum of `amount_cents` over its lines whose `direction` is `CREDIT_BUYER`, `total_seller_credits_cents` as the same sum over `CREDIT_SELLER` lines, and `net_amount_cents` as buyer credits minus seller credits, so a negative net means the buyer owes the seller. The acquisition's `net_proration_cents` is the sum of `net_amount_cents` over its statements in `APPROVED` or `SETTLED` status — drafts, reviewed, and superseded statements are excluded — and is zero when no such statement exists.

Day attribution follows the closing convention: the seller is responsible through the day before `closing_date`, and the buyer owns the closing day itself. Seller days count the calendar days from the period start through the day before closing; buyer days count from the closing date through the period end, closing day included. Rounding order is pinned: each daily rate is rounded half up to integer cents first, then multiplied by whole days exactly, and statement totals are exact integer sums of the per-line rounded amounts. Sum-then-round is forbidden.

Generated lines are emitted in a deterministic order, and a line whose input set is empty is omitted rather than emitted at zero. First come the rent lines, one per non-`EXCLUDED` unit whose current lease stands `AUDITED`, `RESOLVED`, or `WAIVED`, ordered by `unit_number` ascending with ties broken by the lease's `created_at` ascending, each with `direction` `CREDIT_BUYER` and `line_type` `RENT`. Under `ACTUAL_365` the daily rate is the lease's `contract_rent_cents` times twelve divided by 365, rounded half up, and the day counts are the real calendar day counts above, with the period for a rent line being the calendar month containing `closing_date`, first day through last. Under `BANKERS_30_360` the daily rate is `contract_rent_cents` divided by 30, rounded half up, the period is treated as a 30-day month, seller days equal the closing day-of-month minus one, and buyer days equal 30 minus the closing day-of-month plus one; identical inputs therefore produce different amounts under the two methods. The rent line amount is the daily rate times buyer days. Next comes a single tax line of type `TAX` and direction `CREDIT_BUYER`, which requires an approved tax reassessment projection to exist and is the projected `projected_annual_tax_cents` multiplied by the seller days year-to-date — calendar days from January 1 of the closing year through the day before closing — divided by 365, rounded half up. Then the prepaid-expense lines, `CREDIT_SELLER`, ordered by the source entity's `created_at` ascending: per assumed service contract whose `prepaid_through_date` falls after closing, the daily rate is `monthly_cost_cents` times twelve divided by 365 rounded half up, and the days run from the day after closing through the `prepaid_through_date`; per assumed insurance policy whose `prepaid_through_date` falls after closing, the daily rate is `annual_premium_cents` divided by 365 rounded half up over the same day span. Then a single deposit-transfer line of type `DEPOSIT_TRANSFER` and direction `CREDIT_BUYER`, summing `verified_amount_cents` plus `accrued_interest_cents` over every deposit ledger entry in `ESCROW_QUEUED` or `TRANSFERRED`. Last, a single payroll line of type `PAYROLL` and direction `CREDIT_BUYER`, summing `assumed_pto_liability_cents` over employee decisions with `decision` `RETAIN` in `APPROVED`, `NOTIFIED`, or `EFFECTIVE` status.

Each line belongs to its statement through `statement_id` and carries a `line_type` of `RENT`, `TAX`, `PREPAID_EXPENSE`, `DEPOSIT_TRANSFER`, `PAYROLL`, or `ADJUSTMENT` together with a `direction`. Each line also records its `source_kind` — `GENERATED` for the lines above, `MANUAL` for operator-appended ones — plus a polymorphic `source_ref_type` naming the source entity kind (`LEASE_FILE`, `TAX_PROJECTION`, `SERVICE_CONTRACT`, `INSURANCE_POLICY`, `DEPOSIT_ENTRY`, `EMPLOYEE_DECISION`, or `ADJUSTMENT`) and the `source_ref_id` of the source entity, which is null for aggregate lines such as the single tax, deposit-transfer, and payroll lines. While a statement is `DRAFT`, an `UnderwritingManager` may append a manual line by supplying `expected_statement_version` per §2.6 together with the `line_type`, `direction`, `amount_cents`, and an optional free-text `memo`; the append recomputes the statement's totals and increments the statement's `version` by one. Statements and lines list by `acquisition_id`, `status`, and `statement_type`.

Statements clear three segregation-of-duties gates in sequence. Submitting for review moves `DRAFT` to `REVIEWED`, requires the caller to differ from `created_by_user_id` (else `ERR_SOD_VIOLATION`), and stamps `reviewed_by_user_id`. Sending back returns `REVIEWED` to `DRAFT` with an optional `reason` and clears `reviewed_by_user_id`. Approval moves `REVIEWED` to `APPROVED` and enforces three checks: the caller must differ from both `created_by_user_id` and `reviewed_by_user_id` (else `ERR_SOD_VIOLATION`); a snapshot-drift check regenerates the statement's generated lines from live data with the pinned formulas and rejects any drift with `ERR_STATEMENT_DRIFT` — this is where statements referencing a since-superseded tax projection surface; and an approved tax reassessment projection must exist for the acquisition (else `ERR_TAX_PROJECTION_NOT_APPROVED`). The drift check compares stored lines against the regenerated set line by line: every stored line whose `source_kind` is `GENERATED` and whose `line_type` is not `ADJUSTMENT` must find a regenerated line with the same `line_type`, `direction`, `source_ref_type`, and `source_ref_id` carrying an equal `amount_cents`, and a missing counterpart or an amount mismatch is drift. Operator-appended `MANUAL` lines and `ADJUSTMENT` lines posted by an adjustment apply are never part of the comparison; a regenerated line with no stored counterpart does not by itself constitute drift; and a statement holding no stored generated non-`ADJUSTMENT` lines — such as a `POST_CLOSING_TRUEUP` statement created by an adjustment apply, which carries only `ADJUSTMENT` lines — always passes the drift check. Approval also re-derives the acquisition's `net_proration_cents` from this statement. An approve attempted on a statement not in `REVIEWED` is rejected with `ERR_STATEMENT_NOT_REVIEWED`.

Settlement belongs to the `EscrowOfficer` and moves `APPROVED` to `SETTLED`. Only `FINAL_CLOSING` and `POST_CLOSING_TRUEUP` statements are settlable — settling a `DRAFT_CLOSING` is rejected with `ERR_STATEMENT_NOT_SETTLABLE` — and the acquisition must be `CLOSED` (else `ERR_ACQUISITION_NOT_CLOSED`). Settlement finalizes the acquisition's `net_proration_cents`.

### 3.9. The Readiness Posture Derivation

The acquisition's `readiness_posture` is a derived aggregate over every child workstream, recomputed whenever a lease file, deposit entry, deficiency finding, walk inspection, concession, or unit status mutates; findings and leases of `EXCLUDED` units are ignored throughout.

The posture is `BLOCKED` when any of three conditions holds: any lease file of a non-excluded unit stands `DISCREPANCY_FLAGGED`; any deposit ledger entry stands `DISPUTED`; or the `deferred_maintenance_total_cents` is strictly greater than 5 percent of the `agreed_purchase_price_cents` — the threshold itself computed as the price times 0.05 rounded half up to integer cents. Failing that, the posture is `AT_RISK` when any of three conditions holds: the deferred-maintenance total is strictly greater than 3 percent of the price (price times 0.03 rounded half up); any walk inspection stands `QA_REJECTED`; or any concession stands `PENDING`. Otherwise the posture is `ON_TRACK`. Both threshold comparisons are strict: a deferred-maintenance total exactly equal to the 3-percent or 5-percent threshold does not cross it.

### 3.10. Security Deposit Reconciliation and Transfer

The seller's deposit ledger is loaded as one entry per lease with the `seller_stated_amount_cents` — the liability the seller's statement claims, including any interest the seller claims to owe — plus whether the jurisdiction's `interest_required` flag is set and the statutory `annual_interest_rate` as a decimal, defaulting to 0. An entry opens `RECORDED`. The one-entry-per-lease shape is descriptive rather than constrained: multiple entries may be recorded against the same lease, and no duplicate check applies.

Reconciliation by an analyst is allowed only from `RECORDED` (else `ERR_INVALID_STATE_TRANSITION`) and then requires the lease to have completed audit — status `AUDITED`, `RESOLVED`, or `WAIVED`, else `ERR_LEASE_NOT_AUDITED`. The verified principal `verified_amount_cents` is the lease's `deposit_amount_cents`. Accrued interest runs from the lease's `lease_start_date` to the acquisition's `closing_date`, the day count being the calendar days between those dates with the closing date exclusive of the start. When `interest_required` is false, `accrued_interest_cents` is zero. Under the acquisition's default `DAILY_ACCRUAL` method, the accrual is `verified_amount_cents` times `annual_interest_rate` times the day count divided by 365, rounded half up — interest accrues from day one. Under `SIMPLE_ANNUAL`, only whole elapsed anniversary years accrue: the whole-year count is the day count divided by 365 rounded down, and the accrual is `verified_amount_cents` times `annual_interest_rate` times that whole-year count, rounded half up — so a 364-day-old deposit accrues nothing while a 365-day-old deposit accrues one full year. The entry's `variance_cents` is `verified_amount_cents` plus `accrued_interest_cents` minus `seller_stated_amount_cents`. A zero variance lands the entry `RECONCILED`, recomputes the unit's `deposit_reconciled` flag, and recomputes the acquisition's `deposit_variance_cents` and posture. A nonzero variance lands the entry `DISPUTED` instead, recomputes the acquisition rollup, and forces `readiness_posture` to `BLOCKED` while any disputed entry remains. The acquisition's `deposit_variance_cents` is the sum of `variance_cents` over entries in `DISPUTED` status.

Resolving a dispute supplies an `adjusted_verified_amount_cents` and an optional `note`; the entry's `verified_amount_cents` is replaced with the adjusted value, the variance is recomputed under the same formula, and the resolution succeeds only when the recomputed variance is exactly zero — otherwise it is rejected with `ERR_DEPOSIT_VARIANCE_UNRESOLVED`. The replacement and recomputation are written to the stored entry even when the resolution is rejected, so a failed attempt leaves the entry `DISPUTED` while showing the adjusted `verified_amount_cents` and the recomputed `accrued_interest_cents` and `variance_cents`. A successful resolution moves the entry from `DISPUTED` to `RECONCILED` and recomputes the unit flag and both acquisition rollups.

Once the acquisition reaches `PRE_CLOSING` — queueing earlier is rejected with `ERR_ACQUISITION_NOT_PRE_CLOSING` — an `EscrowOfficer` queues each reconciled entry for escrow, moving it to `ESCROW_QUEUED`. At closing, queued entries transfer per the §3.1 cascade, each newly `TRANSFERRED` entry feeding the regenerated deposit-transfer line on the final statement.

### 3.11. Employee Retention, Severance, and PTO

Staffing decisions are proposed by an `HRPartner` with the `acquisition_id`, an `employee_ref`, the on-site `position`, the original `hire_date`, the current `annual_salary_cents`, the `accrued_pto_hours` unused, a `decision` of `RETAIN`, `TERMINATE`, or `TRANSFER`, the `notice_date` on which notice was or will be delivered, the `effective_date` on which the decision takes effect, and an optional `required_notice_days` defaulting to 14. The proposal opens `PROPOSED` with `proposed_by_user_id` stamped from the caller.

Approval belongs to an `UnderwritingManager` and enforces its checks in a fixed order: the acquisition must be `IN_DILIGENCE` (else `ERR_ACQUISITION_NOT_IN_DILIGENCE`); the approver must differ from `proposed_by_user_id` (else `ERR_SOD_VIOLATION`); and the notice window must satisfy the statutory minimum — the calendar days from `notice_date` to `effective_date` must be at least `required_notice_days`, else `ERR_NOTICE_PERIOD_INSUFFICIENT`. Approval computes the compensation package and lands the decision `APPROVED` with `approved_by_user_id` recorded.

Compensation derives from tenure and two rounded rates. Tenure in years is the calendar days from `hire_date` to `effective_date` divided by 365 and rounded down. The weekly rate is `annual_salary_cents` divided by 52 rounded half up; the hourly rate is `annual_salary_cents` divided by 2080 rounded half up, both rounded before any multiplication. A `RETAIN` decision owes nothing: `severance_cents` and `pto_payout_cents` are zero, and `assumed_pto_liability_cents` records the PTO liability the buyer assumes — `accrued_pto_hours` times the hourly rate, rounded half up. A `TERMINATE` or `TRANSFER` decision earns tenure-tiered severance: zero weeks for tenure under one year, one week for tenure of one or two years, two weeks for three to five years, and three weeks for six or more years, so `severance_cents` is the severance weeks times the weekly rate. Its `pto_payout_cents` is `accrued_pto_hours` times the hourly rate, rounded half up, and its `assumed_pto_liability_cents` is zero. A cap binds the sum: when severance plus PTO payout exceeds eight times the weekly rate, the PTO payout is reduced so the two together equal exactly eight weekly rates.

The acquisition's `payroll_accrual_cents` sums `severance_cents` plus `pto_payout_cents` over decisions with `decision` `TERMINATE` or `TRANSFER` in `APPROVED` or `NOTIFIED` status. From `APPROVED`, the HR partner notifies the employee, moving the decision to `NOTIFIED`, and once the logical clock reaches the `effective_date` — marking earlier is rejected with `ERR_NOT_YET_EFFECTIVE` — marks it `EFFECTIVE`, at which point the decision leaves the accrual set and `payroll_accrual_cents` recomputes downward. A manager may also reject a proposal outright into the terminal `REJECTED` state. Rescission by the HR partner — or automatically when the acquisition terminates — moves an `APPROVED` or `NOTIFIED` decision to `RESCINDED` and removes its payroll-accrual contribution as compensation, though the computed `severance_cents` and `pto_payout_cents` remain on the record for audit. `EFFECTIVE`, `REJECTED`, and `RESCINDED` are terminal.

### 3.12. Post-Closing True-Up Adjustments

After closing, either side may assert corrections within the true-up window. An `AcquisitionsAnalyst` asserts an adjustment with the `acquisition_id`, an `adjustment_type` of `COLLECTION_LOSS`, `TAX_RECALC`, `DEPOSIT_SHORTFALL`, or `EXPENSE_RECON`, the asserted `amount_cents`, and a `direction` of `CREDIT_BUYER` or `CREDIT_SELLER`. Assertion requires the acquisition to be `CLOSED` (else `ERR_ACQUISITION_NOT_CLOSED`) and requires the logical clock to be on or before `closing_executed_at` plus `true_up_window_days` days — an assertion after the window is rejected with `ERR_TRUE_UP_WINDOW_EXPIRED`. The adjustment opens `ASSERTED` with `asserted_date` stamped from the clock.

Evidence, supplied by an analyst as an `evidence_note` together with an optional corrected `amount_cents`, moves the adjustment to `EVIDENCED`. When the corrected amount is supplied it replaces the asserted amount before any cap check runs. Collection-loss adjustments follow a waterfall: post-closing resident collections apply to the oldest pre-closing arrears first, ordered by each charge's due date ascending with ties broken by the charge's creation time ascending, and the claimable cap is the lesser of `pre_closing_arrears_cents` (the tenant arrears existing at closing) and `collections_applied_cents` (the post-closing collections applied to those arrears). Evidencing a collection-loss adjustment whose amount exceeds that cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE` (HTTP 422); the evidence step accepts the two collection inputs `pre_closing_arrears_cents` and `collections_applied_cents` alongside the note, and an omitted collection input is treated as zero, so a collection-loss adjustment evidenced without them is capped at zero. The cap applies to the `COLLECTION_LOSS` type only.

From `EVIDENCED` the adjustment forks. Acceptance by an `UnderwritingManager` moves it to `ACCEPTED`. Dispute with a `reason` moves it to `DISPUTED`, from which resolution supplies an agreed `resolved_amount_cents` and lands it `RESOLVED`. The fork joins at application: applying an `ACCEPTED` adjustment posts its `amount_cents`; applying a `RESOLVED` one posts its `resolved_amount_cents` instead. Application lands the adjustment in the terminal `APPLIED` state and posts to the true-up ledger: if no `POST_CLOSING_TRUEUP` statement in `DRAFT` exists for the acquisition, one is created with its `day_count_method` copied from the acquisition's latest `FINAL_CLOSING` statement by `created_at` and its `created_by_user_id` stamped with the applying caller, and an `ADJUSTMENT`-type line with `source_kind` `GENERATED`, `source_ref_type` `ADJUSTMENT`, and `source_ref_id` naming the applied adjustment is appended carrying the posted amount, after which the statement's totals recompute.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource — including every state transition — return `200 OK`. Path identifiers are validated left-to-right per §2.4, and the authorization column lists the only roles permitted beyond the universal read access shared by every role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/acquisitions` | Create an acquisition diligence project | AcquisitionsAnalyst |
| GET | `/acquisitions` | List acquisitions (paginated, filterable by status) | Any |
| GET | `/acquisitions/{id}` | Read one acquisition including computed rollups and posture | Any |
| PATCH | `/acquisitions/{id}` | Amend closing date, estimate basis, or interest method while DRAFT or IN_DILIGENCE | UnderwritingManager |
| POST | `/acquisitions/{id}/kickoff` | Move DRAFT to IN_DILIGENCE | UnderwritingManager |
| POST | `/acquisitions/{id}/complete-diligence` | Move IN_DILIGENCE to DILIGENCE_COMPLETE behind posture and audit gates | UnderwritingManager |
| POST | `/acquisitions/{id}/advance-to-pre-closing` | Move DILIGENCE_COMPLETE to PRE_CLOSING behind the approved-draft-statement gate | UnderwritingManager |
| POST | `/acquisitions/{id}/execute-closing` | Move PRE_CLOSING to CLOSED; runs the deposit/contract/policy transfer cascade | UnderwritingManager |
| POST | `/acquisitions/{id}/settle` | Move CLOSED to SETTLED after the true-up window with statements settled and adjustments terminal | EscrowOfficer |
| POST | `/acquisitions/{id}/terminate` | Terminate from any pre-closing phase; rescinds decisions and (from PRE_CLOSING) force-cancels contracts | UnderwritingManager |
| POST | `/acquisitions/units` | Register a unit | AcquisitionsAnalyst |
| GET | `/acquisitions/units` | List units; filterable by acquisition and status | Any |
| GET | `/acquisitions/units/{id}` | Read one unit with readiness flags | Any |
| POST | `/acquisitions/units/{id}/exclude` | Exclude a REGISTERED or CLEARING unit from scope | AcquisitionsAnalyst |
| POST | `/acquisitions/lease-files` | Upload a lease file, optionally superseding the unit's current lease | AcquisitionsAnalyst |
| GET | `/acquisitions/lease-files` | List lease files; filterable by unit, status, or superseding lease | Any |
| GET | `/acquisitions/lease-files/{id}` | Read one lease file | Any |
| GET | `/acquisitions/units/{id}/lease-files` | List lease files for a unit | Any |
| POST | `/acquisitions/lease-files/{id}/audit` | Audit an UPLOADED lease against the unit's rent roll entry | AcquisitionsAnalyst |
| POST | `/acquisitions/lease-files/{id}/flag` | Re-flag an AUDITED or RESOLVED lease (revision loop) | AcquisitionsAnalyst |
| POST | `/acquisitions/lease-files/{id}/resolve` | Resolve a flagged lease, optionally correcting the contract rent | AcquisitionsAnalyst |
| POST | `/acquisitions/lease-files/{id}/waive` | Waive a flagged lease's variance | UnderwritingManager |
| POST | `/acquisitions/rent-roll-entries` | Record the seller's rent-roll line for a unit | AcquisitionsAnalyst |
| GET | `/acquisitions/units/{id}/rent-roll-entries` | List rent roll entries for a unit | Any |
| POST | `/acquisitions/concessions` | Record a concession on a lease | AcquisitionsAnalyst |
| GET | `/acquisitions/lease-files/{id}/concessions` | List concessions for a lease | Any |
| POST | `/acquisitions/concessions/{id}/verify` | Verify a pending concession with an accepted value | AcquisitionsAnalyst |
| POST | `/acquisitions/concessions/{id}/reject` | Reject a pending concession | AcquisitionsAnalyst |
| POST | `/acquisitions/inspections` | Schedule a unit walk | PropertyOperationsLead |
| GET | `/acquisitions/inspections/{id}` | Read one inspection | Any |
| GET | `/acquisitions/units/{id}/inspections` | List inspections for a unit | Any |
| POST | `/acquisitions/inspections/{id}/complete` | Complete a scheduled walk with rating and no-findings declaration | PropertyOperationsLead |
| POST | `/acquisitions/inspections/{id}/qa-accept` | QA-accept a completed walk; cascades findings into the rollup | PropertyOperationsLead |
| POST | `/acquisitions/inspections/{id}/qa-reject` | QA-reject a completed walk | PropertyOperationsLead |
| POST | `/acquisitions/inspections/{id}/reschedule` | Reschedule a rejected walk with a fresh window | PropertyOperationsLead |
| POST | `/acquisitions/findings` | Record a deficiency finding on a COMPLETED inspection | PropertyOperationsLead |
| GET | `/acquisitions/inspections/{id}/findings` | List findings for an inspection | Any |
| POST | `/acquisitions/findings/{id}/verify` | Verify an OPEN or DISPUTED finding into the rollup | PropertyOperationsLead |
| POST | `/acquisitions/findings/{id}/dispute` | Dispute a verified finding out of the rollup | UnderwritingManager |
| POST | `/acquisitions/findings/{id}/exclude` | Exclude an OPEN or DISPUTED finding | PropertyOperationsLead |
| POST | `/acquisitions/utility-records` | Record a utility or expense month | AcquisitionsAnalyst |
| GET | `/acquisitions/utility-records` | List utility records; filterable | Any |
| GET | `/acquisitions/utility-records/{id}` | Read one utility record | Any |
| GET | `/acquisitions/{id}/expense-summary` | Trailing-12 raw and normalized totals per category plus outlier count | Any |
| POST | `/acquisitions/{id}/tax-projections` | Create a tax reassessment projection (OCC-guarded) | AcquisitionsAnalyst |
| GET | `/acquisitions/tax-projections` | List projections; filterable | Any |
| GET | `/acquisitions/tax-projections/{id}` | Read one projection | Any |
| POST | `/acquisitions/tax-projections/{id}/compute` | Compute a DRAFT projection | AcquisitionsAnalyst |
| POST | `/acquisitions/tax-projections/{id}/approve` | Approve a COMPUTED projection, superseding others | UnderwritingManager |
| POST | `/acquisitions/tax-projections/{id}/revise` | Return a COMPUTED projection to DRAFT | UnderwritingManager |
| POST | `/acquisitions/deposits` | Record a seller-stated deposit liability against a lease | AcquisitionsAnalyst |
| GET | `/acquisitions/lease-files/{id}/deposits` | List deposit entries for a lease | Any |
| POST | `/acquisitions/deposits/{id}/reconcile` | Reconcile a recorded deposit against the lease and interest rules | AcquisitionsAnalyst |
| POST | `/acquisitions/deposits/{id}/resolve-dispute` | Resolve a disputed deposit with an adjusted verified amount | AcquisitionsAnalyst |
| POST | `/acquisitions/deposits/{id}/queue-escrow` | Queue a reconciled deposit for escrow transfer | EscrowOfficer |
| POST | `/acquisitions/employee-decisions` | Propose a retention, termination, or transfer decision | HRPartner |
| GET | `/acquisitions/employee-decisions` | List employee decisions; filterable | Any |
| GET | `/acquisitions/employee-decisions/{id}` | Read one employee decision | Any |
| POST | `/acquisitions/employee-decisions/{id}/approve` | Approve a proposed decision; computes severance and PTO | UnderwritingManager |
| POST | `/acquisitions/employee-decisions/{id}/reject` | Reject a proposed decision | UnderwritingManager |
| POST | `/acquisitions/employee-decisions/{id}/notify` | Record notice delivery for an approved decision | HRPartner |
| POST | `/acquisitions/employee-decisions/{id}/mark-effective` | Mark a notified decision effective once its date arrives | HRPartner |
| POST | `/acquisitions/employee-decisions/{id}/rescind` | Rescind an approved or notified decision | HRPartner |
| POST | `/acquisitions/service-contracts` | Register a vendor service contract | VendorManager |
| GET | `/acquisitions/service-contracts` | List service contracts; filterable | Any |
| GET | `/acquisitions/service-contracts/{id}` | Read one service contract | Any |
| POST | `/acquisitions/service-contracts/{id}/begin-review` | Begin review of an identified contract | VendorManager |
| POST | `/acquisitions/service-contracts/{id}/assume` | Assume a reviewed contract into the buyer's program | VendorManager |
| POST | `/acquisitions/service-contracts/{id}/send-notice` | Send cancellation notice before the decision deadline | VendorManager |
| POST | `/acquisitions/service-contracts/{id}/mark-cancelled` | Mark a noticed contract cancelled once its effective date arrives | VendorManager |
| POST | `/acquisitions/service-contracts/{id}/renew` | Renew a reviewed contract | VendorManager |
| POST | `/acquisitions/insurance-policies` | Register an insurance policy with three-year loss runs | AcquisitionsAnalyst |
| GET | `/acquisitions/insurance-policies` | List policies; filterable | Any |
| GET | `/acquisitions/insurance-policies/{id}` | Read one policy | Any |
| POST | `/acquisitions/insurance-policies/{id}/review-loss-runs` | Review loss runs; computes loss ratio and risk tier | UnderwritingManager |
| POST | `/acquisitions/insurance-policies/{id}/assume` | Assume a reviewed policy; HIGH tier requires an override | UnderwritingManager |
| POST | `/acquisitions/insurance-policies/{id}/exclude` | Exclude a documented or reviewed policy | UnderwritingManager |
| POST | `/acquisitions/{id}/proration-statements` | Generate a proration statement (OCC-guarded, phase-gated) | UnderwritingManager |
| GET | `/acquisitions/proration-statements` | List statements; filterable | Any |
| GET | `/acquisitions/proration-statements/{id}` | Read one statement with totals | Any |
| POST | `/acquisitions/proration-statements/{id}/lines` | Append a manual line to a DRAFT statement (OCC-guarded) | UnderwritingManager |
| GET | `/acquisitions/proration-statements/{id}/lines` | List lines of a statement | Any |
| POST | `/acquisitions/proration-statements/{id}/submit-review` | Submit a draft statement for review | UnderwritingManager |
| POST | `/acquisitions/proration-statements/{id}/send-back` | Send a reviewed statement back to draft | UnderwritingManager |
| POST | `/acquisitions/proration-statements/{id}/approve` | Approve a reviewed statement behind SoD, drift, and tax gates | UnderwritingManager |
| POST | `/acquisitions/proration-statements/{id}/settle` | Settle an approved final or true-up statement once the acquisition is closed | EscrowOfficer |
| POST | `/acquisitions/adjustments` | Assert a post-closing adjustment within the true-up window | AcquisitionsAnalyst |
| GET | `/acquisitions/adjustments` | List adjustments; filterable | Any |
| GET | `/acquisitions/adjustments/{id}` | Read one adjustment | Any |
| POST | `/acquisitions/adjustments/{id}/evidence` | Evidence an asserted adjustment; collection-loss cap enforced | AcquisitionsAnalyst |
| POST | `/acquisitions/adjustments/{id}/accept` | Accept an evidenced adjustment | UnderwritingManager |
| POST | `/acquisitions/adjustments/{id}/dispute` | Dispute an evidenced adjustment | UnderwritingManager |
| POST | `/acquisitions/adjustments/{id}/resolve` | Resolve a disputed adjustment at an agreed amount | UnderwritingManager |
| POST | `/acquisitions/adjustments/{id}/apply` | Apply an accepted or resolved adjustment to the true-up statement | UnderwritingManager |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock; runs the auto-renew sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_ACQUISITION_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_LEASE_FILE_NOT_FOUND` | 404 |
| `ERR_CONCESSION_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_UTILITY_RECORD_NOT_FOUND` | 404 |
| `ERR_TAX_PROJECTION_NOT_FOUND` | 404 |
| `ERR_DEPOSIT_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_DECISION_NOT_FOUND` | 404 |
| `ERR_SERVICE_CONTRACT_NOT_FOUND` | 404 |
| `ERR_INSURANCE_POLICY_NOT_FOUND` | 404 |
| `ERR_PRORATION_STATEMENT_NOT_FOUND` | 404 |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_ACQUISITION_NOT_IN_DILIGENCE` | 409 |
| `ERR_ACQUISITION_NOT_PRE_CLOSING` | 409 |
| `ERR_ACQUISITION_NOT_CLOSED` | 409 |
| `ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE` | 409 |
| `ERR_STATEMENT_NOT_REVIEWED` | 409 |
| `ERR_STATEMENT_NOT_SETTLABLE` | 409 |
| `ERR_LEASE_NOT_AUDITED` | 409 |
| `ERR_TAX_PROJECTION_NOT_APPROVED` | 409 |
| `ERR_NO_APPROVED_DRAFT_STATEMENT` | 409 |
| `ERR_NO_APPROVED_FINAL_STATEMENT` | 409 |
| `ERR_DEPOSITS_NOT_QUEUED` | 409 |
| `ERR_OPEN_DECISIONS_REMAIN` | 409 |
| `ERR_OPEN_SERVICE_CONTRACTS_REMAIN` | 409 |
| `ERR_UNRESOLVED_AUDIT_ITEMS` | 409 |
| `ERR_FINAL_STATEMENT_NOT_SETTLED` | 409 |
| `ERR_TRUEUP_STATEMENT_NOT_SETTLED` | 409 |
| `ERR_OPEN_ADJUSTMENTS_REMAIN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_SUPERSEDE_TARGET_NOT_CURRENT` | 409 |
| `ERR_RENT_ROLL_ENTRY_MISSING` | 422 |
| `ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE` | 409 |
| `ERR_ACQUISITION_BLOCKED` | 409 |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 |
| `ERR_ACTIVE_LEASE_EXISTS` | 409 |
| `ERR_RENT_ROLL_ENTRY_EXISTS` | 409 |
| `ERR_UTILITY_RECORD_EXISTS` | 409 |
| `ERR_INSPECTION_NOT_COMPLETED` | 409 |
| `ERR_FINDINGS_REQUIRED` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_CONCESSION_OVERLAP` | 409 |
| `ERR_NOTICE_WINDOW_MISSED` | 409 |
| `ERR_NOTICE_PERIOD_INSUFFICIENT` | 409 |
| `ERR_NOT_YET_EFFECTIVE` | 409 |
| `ERR_CANCELLATION_NOT_YET_EFFECTIVE` | 409 |
| `ERR_TRUE_UP_WINDOW_EXPIRED` | 409 |
| `ERR_TRUE_UP_WINDOW_OPEN` | 409 |
| `ERR_STATEMENT_DRIFT` | 409 |
| `ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE` | 422 |
| `ERR_DEPOSIT_VARIANCE_UNRESOLVED` | 409 |
