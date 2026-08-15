# Planned Giving & Bequest Administration API — Product Requirements Document

## 1. Introduction

A university planned giving office operates at the intersection of donor stewardship, actuarial science, and regulatory compliance. Charitable gift annuities, charitable remainder trusts, and testamentary bequests are promised years — sometimes decades — before their value arrives, and every stage in between is governed by hard rules: payout rates bounded by statute, charitable deductions subject to a ten-percent remainder test, annuity reserves that must demonstrably cover the liability they back, and probate processes with court-imposed deadlines. This document specifies an API that runs that office end to end: modeling gift illustrations for prospective donors, executing binding gift agreements, tracking beneficiary paperwork, servicing annuity payment schedules, monitoring matured estates through probate, receiving and liquidating contributed assets, and crediting donor-restricted funds in accordance with documented intent.

Two concerns shape the design throughout. First, **segregation of duties**: the officer who illustrates a gift may not execute it, the officer who records an estate may not approve its distribution, and the officer who prepares an actuarial valuation may not post it. Second, **a single source of actuarial truth**: every deduction, liability, and reserve requirement is computed under a pinned discount-rate table whose coverage windows are strictly non-overlapping, so that two operators can never book the same gift under different rate assumptions. All monetary amounts are integer cents; all rates are integer basis points.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly five roles: `GiftOfficer`, `GiftAdministrator`, `ComplianceOfficer`, `EstateManager`, and `FinanceSteward`. A request missing either header, or presenting an `X-User-Role` value outside these five names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the roles authorized for the target endpoint — including per-action role restrictions on shared transition endpoints — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For all five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources for audit and segregation-of-duties purposes — as `created_by_user_id` on an `Illustration` or a `ValuationRun`, as `executed_by_user_id` on a `GiftAgreement`, as `recorded_by_user_id` on an `Estate`, and as `posted_by_user_id` on a posted `ValuationRun` — but it never compares `X-User-ID` against any entity's `id`, and there is no per-resource ownership model.

Three operations enforce segregation of duties by comparing the actor's `X-User-ID` against the recorded originator; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). First, executing a gift agreement that was created by booking an illustration requires the executing `GiftAdministrator` to differ from the illustration's `created_by_user_id`. Second, posting a valuation run requires the posting `ComplianceOfficer` to differ from the run's `created_by_user_id`. Third, beginning distribution on an estate requires the acting `EstateManager` to differ from the estate's `recorded_by_user_id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. One deliberate exception: the annuity-payment list is deterministically sorted by `period_index` ascending within an agreement. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled Sweeps

All time-dependent behavior in the system is driven by a **logical clock**, never by wall-clock time. At server startup, before any client call, the logical clock reads exactly `2026-08-01T00:00:00Z`. An administrative, test-driving capability — available to all five roles — advances the clock: the caller supplies a `to_iso8601` instant, and the response reports the resulting `current_utc`. Every `due_date`, deferral boundary, probate deadline, execution timestamp, and posting timestamp in the system is evaluated against this clock.

Advancing the clock triggers two automatic sweeps, applied atomically with the clock write. First, every annuity payment in `SCHEDULED` status whose `due_date` is at or before the current clock time flips to `DUE`, and every payment in `DEFERRED` status whose `defer_until` is at or before the current clock time flips back to `DUE`. Second, every probate milestone in `PENDING` or `FILED` status whose `due_date` is strictly before the current clock time flips to `OVERDUE`. The same payment sweep is also applied lazily whenever a payment (or a list of payments) is read, so a client never observes a stale `SCHEDULED` payment whose due date has passed. Each resource flipped by a sweep has its `version` incremented.

### 2.5. Common Resource Properties

Every resource in the system — donors, rate tables, illustrations, gift agreements, beneficiary designations, gift assets, annuity payments, the reserve fund, estates, probate milestones, funds, and valuation runs — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at creation and increments by one on **every** mutation of the resource, including mutations caused by cascades originating elsewhere (for example, a donor-death cascade bumps the `version` of every matured agreement and every lapsed payment it touches, and a reserve-fund recompute bumps the fund's `version`).

Because the resource topology is flat — peer resources joined by foreign-key references rather than nested URL ownership — a resource is always addressed by its own top-level identifier.

### 2.6. Monetary Precision, Rounding, and Pinned Evaluation Orders

All monetary values are integer cents. All rates and coverage ratios are integer basis points (500 basis points is 5.00%; 10000 basis points is 100%). Rounding follows a single convention: **round half up** to the nearest cent at each pinned step, with one deliberate exception noted below.

Two rounding-order commitments are load-bearing. In annuity payment schedules, each payment's `amount_cents` is independently rounded from the annual annuity, and there is **no cumulative true-up** on any payment — the sum of a schedule's payments may therefore differ from the annual annuity multiplied by the number of years by a few cents. In estate liquidation, each asset's `net_proceeds_cents` is rounded per asset at liquidation time, and the estate's `gross_proceeds_cents` is then the sum of those per-asset values: per-asset first, then sum. The one exception to half-up rounding is the reserve coverage ratio `booked_coverage_bps`, which is **floored** to integer basis points — a deficient ratio never rounds up into compliance.

Actuarial discount factors are carried in full floating-point precision with no intermediate rounding; only the final present-value figure is rounded half-up to whole cents.

### 2.7. Discount-Rate Windows and Pinning

A `RateTable` carries a `label`, a `discount_rate_bps` rate in basis points, and an effectiveness window defined by `effective_from` (inclusive) and `effective_to` (exclusive) — a **half-open interval**. A null `effective_to` reads as open-ended, extending to infinity. Among tables in `DRAFT` or `ACTIVE` status, no two windows may intersect; adjacency — one table's `effective_from` equal to another's `effective_to` — is **not** an overlap. A violation, detected at table creation or at activation, is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 409).

Illustrations and directly created gift agreements pin a rate table at creation: the system selects the `ACTIVE` table whose half-open window covers the supplied `funding_month` and stores it as `rate_table_id`. If no `ACTIVE` table covers that month, creation fails with `ERR_RATE_TABLE_NOT_ACTIVE` (HTTP 409). Retiring a table does not disturb agreements already pinning it, but execution re-validates the pin: at execute time the pinned table must still be `ACTIVE` and its window must still cover the agreement's `funding_month`, or the execution is rejected with `ERR_RATE_TABLE_NOT_ACTIVE`.

### 2.8. The Charitable Gift Annuity Reserve and Its Two Coverage Bases

The system maintains a single `ReserveFund` — a singleton ledger instantiated at server startup with `name` equal to `CGA_RESERVE`, `balance_cents` equal to zero, and `posture` equal to `SOLVENT`. The fund's `balance_cents` is the cash actually held in reserve; it moves only through manual adjustments, through credits when assets linked to CGA agreements are liquidated, and through debits when a CGA agreement's surrender value is paid out at termination.

Two coverage targets are recomputed whenever the balance or any CGA agreement's status or `reserve_requirement_cents` changes, in this pinned evaluation order (which deliberately breaks the circular dependency between posture and targets). First, `booked_target_cents` is the sum of `reserve_requirement_cents` over agreements whose `vehicle_type` is `CGA` and whose `status` is one of `FUNDED`, `ACTIVE`, or `SUSPENDED` — the statutory basis. Second, `projected_target_cents` is `booked_target_cents` plus the sum of `reserve_requirement_cents` over `CGA` agreements in `EXECUTED` status — the forward-looking basis. Third, `booked_coverage_bps` is null when `booked_target_cents` is zero, and otherwise the floored integer value of `balance_cents` times 10000 divided by `booked_target_cents`. Fourth, `posture` is `SOLVENT` when `booked_target_cents` is zero or `booked_coverage_bps` is at least 10000, and `RESERVE_DEFICIENT` otherwise. The boundary is inclusive: coverage of exactly 10000 basis points is solvent, while a balance one cent below target floors to 9999 and is deficient. Whenever the balance, either target, or the posture mutates, the reserve fund's `version` increments.

The posture is a gate, not just a report: while the fund is `RESERVE_DEFICIENT`, executing any new CGA agreement is blocked with `ERR_RESERVE_DEFICIENT` (HTTP 409); CRT and bequest vehicles are unaffected by the posture.

### 2.9. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

Amending a draft gift agreement requires the request to carry `expected_gift_agreement_version`, holding the agreement `version` the client last observed. Because a draft-to-draft amendment changes no status field, a second amendment carrying a previously observed version would otherwise silently apply on top of an intervening amendment; the stale-version check is the only guard. A mismatch with the agreement's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Posting a manual reserve adjustment requires the request to carry `expected_reserve_fund_version`, holding the reserve fund `version` the client last observed. Adjustments legitimately stack — a contribution and a withdrawal both succeed in sequence — so each adjustment must be based on the current version; a stale version proves the client computed its amount from a superseded balance or coverage snapshot. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Validation Priority and Reference Resolution

Every request is validated against an ordered chain of checks, and the **first** failure wins — a request that would fail two checks receives the error of the earlier one. The global priority order is:

1. Authentication: presence of `X-User-ID` and `X-User-Role`, and role membership — `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role is permitted on this endpoint — `ERR_UNAUTHORIZED`.
3. Segregation of duties on the three anchored operations — `ERR_SEGREGATION_OF_DUTIES`.
4. Existence: every path identifier and every foreign-key-valued body field resolves to an existing resource, validated left to right — path parameters first, then body fields — `ERR_NOT_FOUND`.
5. Optimistic concurrency staleness on the two OCC-guarded endpoints — `ERR_STALE_VERSION`.
6. State-machine legality for the requested transition or action — `ERR_INVALID_STATE`, including terminal-state lockdown, re-posting a posted run (`ERR_VALUATION_ALREADY_POSTED`), paying or deferring a payment not in `DUE` (`ERR_PAYMENT_NOT_DUE`), and paying under a suspended agreement (`ERR_AGREEMENT_SUSPENDED`).
7. Donor vital-state compatibility — `ERR_DONOR_STATE_MISMATCH`.
8. The regulatory remainder test — `ERR_REMAINDER_TEST_FAILED`.
9. The regulatory exhaustion test — `ERR_EXHAUSTION_TEST_FAILED`.
10. Verified primary-beneficiary documentation — `ERR_DESIGNATION_NOT_VERIFIED`.
11. Designation document on file — `ERR_DOCUMENT_NOT_RECEIVED`.
12. Vehicle/field consistency — `ERR_BEQUEST_VEHICLE_MISMATCH`.
13. Payout-rate bounds — `ERR_PAYOUT_RATE_OUT_OF_RANGE`.
14. Beneficiary slot occupancy — `ERR_SLOT_OCCUPIED`.
15. Legacy society gates — `ERR_LEGACY_SOCIETY_INELIGIBLE`.
16. Fund uniqueness per agreement — `ERR_FUND_ALREADY_EXISTS`.
17. Rate-table window overlap — `ERR_RATE_WINDOW_OVERLAP`.
18. Rate-table coverage of the funding month — `ERR_RATE_TABLE_NOT_ACTIVE`.
19. Valuation coverage-window overlap — `ERR_VALUATION_WINDOW_OVERLAP`.
20. Valuation-date rate coverage — `ERR_NO_ACTIVE_RATE_TABLE`.
21. Gift-asset parentage — `ERR_ASSET_ORPHAN`.
22. Estate milestone completeness — `ERR_MILESTONES_OPEN`.
23. Estate asset liquidation completeness — `ERR_ASSETS_NOT_LIQUIDATED` (always evaluated after the milestone gate).
24. Real-estate appraisal prerequisite — `ERR_ASSET_KIND_REQUIRES_APPRAISAL`.
25. The CGA reserve gate at execution — `ERR_RESERVE_DEFICIENT`.
26. Withdrawal and surrender solvency — `ERR_INSUFFICIENT_RESERVE_BALANCE`.
27. Estate distribution waterfall solvency — `ERR_DISTRIBUTION_OVERFLOW`.
28. Fund activation minimum — `ERR_FUND_MINIMUM_NOT_MET`.
29. Envelope and schema conformance — `ERR_INVALID_REQUEST`: unknown fields, malformed types, invalid enum members, missing required fields, a `valuation_date` outside its own coverage window, or a `defer_until` not in the future.

Note the deliberate ordering inside the execution gate: the remainder test is evaluated before the exhaustion test, and both are evaluated before the beneficiary-documentation check — so a deduction that fails the ten-percent floor surfaces as `ERR_REMAINDER_TEST_FAILED` even if the designation paperwork is also incomplete.

## 3. Business Logic & Workflows

### 3.1. Donor Records, Legacy Society Stewardship, and the Death Cascade

A `GiftOfficer` registers a donor by supplying the donor's `full_name` and `date_of_birth` (an ISO 8601 date), optionally with a `contact_email`. The donor list can be filtered by `vital_status` and `legacy_society_status`. Each donor record carries two **parallel state axes** that evolve independently on the same row. The vital axis, `vital_status`, begins at `LIVING` and moves to `DECEASED`, which is terminal; the date of death is recorded on `deceased_on` and remains null while the donor is `LIVING`. The stewardship axis, `legacy_society_status`, begins at `NONE` and may move `NONE` → `ENROLLED` → `RECOGNIZED`, may be revoked from either `ENROLLED` or `RECOGNIZED` to `REVOKED`, and supports re-enrollment `REVOKED` → `ENROLLED` under the same eligibility rules as initial enrollment.

Legacy society transitions are requested by a `GiftOfficer` with an `action` of `ENROLL`, `RECOGNIZE`, or `REVOKE`. Enrollment requires the donor to be `LIVING` and to have at least one **documented planned gift** — a gift agreement in `EXECUTED`, `FUNDED`, `ACTIVE`, `SUSPENDED`, `MATURED`, or `SETTLED` status — otherwise the request is rejected with `ERR_LEGACY_SOCIETY_INELIGIBLE` (HTTP 422). Recognition requires the donor to be `ENROLLED` and to have a `documented_gift_total_cents` of at least 10000000 cents (one hundred thousand dollars), an inclusive boundary; `documented_gift_total_cents` is a live-computed field equal to the sum of `gift_amount_cents` over the donor's agreements in exactly that six-status set — `DRAFT`, `WITHDRAWN`, `RESCINDED`, and `TERMINATED` agreements are excluded — and it is recomputed whenever an agreement enters or leaves the set. Revocation is permitted from `ENROLLED` or `RECOGNIZED`. Each legacy transition increments the donor's `version`.

When a donor dies, an `EstateManager` records the death by supplying `deceased_on`; the precondition is that the donor is still `LIVING`. This single call fires a multi-hop cascade, applied atomically:

- The donor's `vital_status` becomes `DECEASED` and `deceased_on` is stored.
- **Hop 1:** for each of the donor's gift agreements, processed in `created_at` ascending order, if the agreement's status is `EXECUTED`, `FUNDED`, `ACTIVE`, or `SUSPENDED` and its `vehicle_type` is `CGA`, `CRT_ANNUITY`, or `CRT_UNITRUST`, the agreement becomes `MATURED`. This is a house rule: annuity vehicles mature on the donor's death regardless of the number of lives on the contract.
- **Hop 2:** for each agreement matured in hop 1, every linked annuity payment in `SCHEDULED`, `DUE`, or `DEFERRED` status becomes `LAPSED` with `lapse_reason` set to `DONOR_DEATH`, and the agreement's `liability_released_cents` and payment-total derived fields are recomputed.
- **Hop 1b:** if a matured agreement's `vehicle_type` is `BEQUEST` and its status was `EXECUTED` or `FUNDED`, it becomes `MATURED` and a new `Estate` is auto-created for the donor, linked to that agreement, starting in `NOTIFIED` status with `notified_on` set to the supplied `deceased_on` and `recorded_by_user_id` set to the acting `EstateManager`.
- **Hop 3:** the reserve fund's `booked_target_cents` is recomputed, because `MATURED` CGA agreements leave the `FUNDED`/`ACTIVE`/`SUSPENDED` inclusion set.
- **Hop 4:** `booked_coverage_bps` and `posture` are recomputed from the new target; the posture may flip from `RESERVE_DEFICIENT` back to `SOLVENT`.

The donor's `version` increments and `updated_at` refreshes; every mutated agreement and payment likewise has its `version` incremented and `updated_at` refreshed.

### 3.2. Discount Rate Tables and Gift Illustrations

A `ComplianceOfficer` authors rate tables. Creation supplies a `label` (for example, "IRS 7520 2026-H1"), a `discount_rate_bps` rate in basis points, an inclusive `effective_from`, and an optional exclusive `effective_to` whose absence makes the window open-ended; the window-overlap rule of §2.7 is enforced at creation. A table begins in `DRAFT`. From `DRAFT`, a transition with `action` `ACTIVATE` moves it to `ACTIVE`, re-checking the window against every other `DRAFT` or `ACTIVE` table (`ERR_RATE_WINDOW_OVERLAP` on intersection). A transition with `action` `RETIRE` moves a `DRAFT` or `ACTIVE` table to the terminal `RETIRED` status; agreements already pinning a retired table are unaffected until they attempt execution, at which point the pin is re-validated (§2.7).

A `GiftOfficer` models a prospective gift by creating an **illustration** for a living donor (a deceased donor is rejected with `ERR_DONOR_STATE_MISMATCH`, HTTP 409). The payload names the `donor_id`, the `vehicle_type` — one of `CGA`, `CRT_UNITRUST`, `CRT_ANNUITY`, or `BEQUEST` — the `gift_amount_cents` principal, and the assumed `funding_month` in `YYYY-MM` format. For annuity vehicles the payload must carry `payout_rate_bps` (required) along with `annuitant_1_age`; a `BEQUEST` illustration must **not** carry `payout_rate_bps`, and violations in either direction are rejected with `ERR_BEQUEST_VEHICLE_MISMATCH` (HTTP 422). Where a payout rate is supplied it must lie within 500 to 5000 basis points inclusive — 500 is accepted and 499 rejected, 5000 is accepted and 5001 rejected — or the request fails with `ERR_PAYOUT_RATE_OUT_OF_RANGE` (HTTP 422). `payment_frequency` is one of `ANNUAL`, `SEMIANNUAL`, `QUARTERLY`, or `MONTHLY`, defaulting to `QUARTERLY`. `lives` is 1 or 2 and defaults to 1; `annuitant_2_age` is required if and only if `lives` is 2. At creation the system pins the `ACTIVE` rate table whose window covers `funding_month` into `rate_table_id`, or rejects the illustration with `ERR_RATE_TABLE_NOT_ACTIVE` when no table covers that month. The illustration list supports filtering by `donor_id`, `rate_table_id`, `supersedes_illustration_id`, and `status`.

An illustration is born `OPEN` and immediately carries two computed figures: `illustrated_annual_annuity_cents` — the provisional annual annuity, null for `BEQUEST` — and `illustrated_deduction_cents`, the provisional charitable deduction computed under the pinned table at illustration time using the same actuarial method described for execution in §3.3. These figures are purely informational. The creator's `X-User-ID` is recorded as `created_by_user_id` and later anchors the segregation-of-duties check at execution.

Illustrations form a self-referential chain. If a new illustration is created with `supersedes_illustration_id` pointing at an existing `OPEN` illustration, the referenced illustration flips to `SUPERSEDED` as a side effect of the creation (its `version` increments). Booking is the other exit: a `GiftOfficer` books an `OPEN` illustration — the donor must still be `LIVING`, else `ERR_DONOR_STATE_MISMATCH` — which moves the illustration to the terminal `BOOKED` status and creates a `GiftAgreement` in `DRAFT`, copying `donor_id`, `vehicle_type`, `gift_amount_cents`, `payout_rate_bps`, `payment_frequency`, `lives`, both annuitant ages, `funding_month`, and the pinned `rate_table_id`, with the new agreement's `illustration_id` pointing back at the source illustration. Both terminal states — `BOOKED` and `SUPERSEDED` — are locked against further transitions with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Gift Agreements: Drafting, Amendment, and Execution

A `GiftAgreement` may also be created directly by a `GiftOfficer`, without any illustration, via a payload mirroring the illustration fields — `donor_id`, `vehicle_type`, `gift_amount_cents`, the conditional `payout_rate_bps`, `payment_frequency`, `lives`, `annuitant_1_age`, `annuitant_2_age`, `funding_month` — plus three intent fields: `restriction_type` (one of `UNRESTRICTED`, `SCHOLARSHIP`, `FACULTY_SUPPORT`, `RESEARCH`, or `CAPITAL`, defaulting to `UNRESTRICTED`), free-text `restriction_text`, and an optional `fund_id` naming the remainder destination. The donor must be `LIVING`, the rate-table pin resolves exactly as for illustrations, and the agreement list can be filtered by `donor_id`, `fund_id`, `illustration_id`, `rate_table_id`, `status`, and `vehicle_type`. The agreement lifecycle spans `DRAFT`, `EXECUTED`, `FUNDED`, `ACTIVE`, `SUSPENDED`, `MATURED`, `SETTLED`, `WITHDRAWN`, `RESCINDED`, and `TERMINATED`, with `SETTLED`, `WITHDRAWN`, `RESCINDED`, and `TERMINATED` terminal.

While an agreement is `DRAFT`, a `GiftAdministrator` may amend it in place. The amendment request must carry `expected_gift_agreement_version` per the OCC rule of §2.9, and may supply new values for `gift_amount_cents`, `payout_rate_bps` (subject to the 500–5000 basis-point band for annuity vehicles), `payment_frequency`, `restriction_type`, `restriction_text`, and `fund_id`. Amending `gift_amount_cents` or `payout_rate_bps` does not recompute any booked economics: `annual_annuity_cents` stays null and all economic recomputation is deferred to execution. A successful amendment increments the agreement's `version`.

Execution is the pivotal, heavily gated transition, performed by a `GiftAdministrator` on a `DRAFT` agreement. The checks apply in the global priority order of §2.10: segregation of duties against the source illustration's `created_by_user_id` when `illustration_id` is set (`ERR_SEGREGATION_OF_DUTIES`); donor vitality (`ERR_DONOR_STATE_MISMATCH` if the donor is not `LIVING`); the regulatory remainder test for annuity vehicles — the booked deduction multiplied by ten must be at least the gift principal, an inclusive ten-percent floor, else `ERR_REMAINDER_TEST_FAILED` (HTTP 422); the exhaustion test, which applies **only** to `CRT_ANNUITY` — the present value of the annuity must not exceed 85% of the gift principal, computed as `gift_amount_cents` times 8500 basis points and rounded half-up, else `ERR_EXHAUSTION_TEST_FAILED` (HTTP 422); the documentation gate — a `VERIFIED` beneficiary designation with `slot` `PRIMARY_1` must exist, else `ERR_DESIGNATION_NOT_VERIFIED` (HTTP 409); vehicle/field consistency, in particular that a `BEQUEST` carries no payout rate, else `ERR_BEQUEST_VEHICLE_MISMATCH`; the pinned rate table must still be `ACTIVE` and covering `funding_month`, else `ERR_RATE_TABLE_NOT_ACTIVE`; and finally, for `CGA` agreements only, the reserve gate — the fund's `balance_cents` must be at least `booked_target_cents` plus the summed `reserve_requirement_cents` of all **other** `EXECUTED` CGA agreements plus this candidate agreement's own requirement, else `ERR_RESERVE_DEFICIENT`. The exhaustion band is deliberately tighter than the remainder ceiling: a present value in the band above 85% and at or below 90% passes the remainder test yet fails exhaustion, so each test exercises independently.

The actuarial method behind these gates works as follows. Let the periodic discount rate be the pinned table's `discount_rate_bps` expressed as a fraction — basis points divided by 10000 — and let the discount factor be the reciprocal of one plus that rate. For an annuitant of a given age, the term length is 100 minus that age, floored at a minimum of 1. The whole-life annuity-immediate factor for a term is one minus the discount factor raised to that term's power, all divided by the rate, carried in full floating-point precision with no intermediate rounding. A single-life gift uses the factor at `annuitant_1_age`; a two-life gift sums the two single-life factors and subtracts the factor evaluated at the older of the two ages. The present value of the annuity obligation is the annual annuity multiplied by that factor, rounded half-up to whole cents. The charitable deduction is `gift_amount_cents` minus that present value, floored at zero — and for `BEQUEST` agreements the deduction is simply the full `gift_amount_cents`, since no annuity offsets it.

A successful execution pins the agreement's booked economics: `annual_annuity_cents` (null for `BEQUEST`); `booked_deduction_cents` per the method above; `actuarial_liability_cents`, the present value of the future annuity obligation under the same factor method; `remainder_value_cents`, defined as `corpus_value_cents` minus `actuarial_liability_cents` floored at zero; `reserve_requirement_cents` for CGA agreements per §3.9 (zero for all other vehicles); and `corpus_value_cents` initialized to `gift_amount_cents`. The system stamps `executed_at` from the logical clock and records the actor as `executed_by_user_id`; the reserve fund's `projected_target_cents` is recomputed as the newly `EXECUTED` CGA joins the projected set, the donor's `documented_gift_total_cents` is recomputed, and the agreement's `version` increments.

From `EXECUTED`, an agreement may be rescinded by a `GiftAdministrator` (action `RESCIND`) only while nothing has been received against it — if any linked gift asset has status `RECEIVED`, `APPRAISED`, `LIQUIDATED`, or `DISTRIBUTED`, the rescission is rejected with `ERR_INVALID_STATE`; a rescinded CGA leaves the projected reserve set, and both `projected_target_cents` and the donor's documented total are recomputed. From `DRAFT`, a `GiftAdministrator` may `WITHDRAW` the agreement to `WITHDRAWN`. Once `ACTIVE`, a `ComplianceOfficer` may `SUSPEND` the agreement — which blocks all payment disbursements on its payments with `ERR_AGREEMENT_SUSPENDED` (HTTP 409) for the duration — and later `RESUME` it back to `ACTIVE`. Any attempt to drive one of these transitions from a state not listed as its source is rejected with `ERR_INVALID_STATE`.

Early termination, performed by a `GiftAdministrator` from `EXECUTED`, `FUNDED`, `ACTIVE`, or `SUSPENDED`, moves the agreement to `TERMINATED` and settles accounts: `surrender_value_cents` is computed as `received_value_cents` minus `total_paid_cents`, floored at zero; for a CGA agreement that surrender value is **debited** from the reserve fund's `balance_cents` with no floor at zero applied — if the balance cannot cover the surrender, the termination is rejected outright with `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422). Every linked payment still in `SCHEDULED`, `DUE`, or `DEFERRED` lapses with `lapse_reason` `TERMINATION`, and the reserve targets, coverage, and posture are recomputed.

Settlement closes the loop for a `MATURED` agreement. A `FinanceSteward` settles it against the fund named by `fund_id`; that fund must exist (else `ERR_NOT_FOUND`) and must not be `CLOSED` (else `ERR_INVALID_STATE`). The fund's `balance_cents` grows by the agreement's `remainder_value_cents` — which is zero for a `BEQUEST`, since bequest value arrives through the estate residual instead — and if the credit lifts a `PROPOSED` fund's balance to at least its `minimum_endowment_cents`, the fund automatically becomes `ENDOWED` (inclusive boundary). Both the agreement's and the fund's `version` increment.

### 3.4. Beneficiary Designations and the Paperwork Gates

Beneficiary paperwork is tracked per agreement through `BeneficiaryDesignation` resources, addressed by `designation_id` and filterable in the list endpoint by `gift_agreement_id`, `slot`, and `status`. A `GiftOfficer` creates a designation by supplying the `gift_agreement_id`, a `slot` of `PRIMARY_1`, `PRIMARY_2`, or `CONTINGENT`, the `beneficiary_name`, and optionally `document_received` (a boolean defaulting to false, recording whether the wet-ink designation document is on file). A designation begins in `DRAFT`, and its lifecycle runs `DRAFT` → `SUBMITTED` → `VERIFIED`, with `REJECTED`, `SUPERSEDED`, and `REVOKED` as additional states and `SUPERSEDED`/`REVOKED` terminal.

Slot discipline is strict: at most one designation per (`gift_agreement_id`, `slot`) pair may be `SUBMITTED` at any moment, and the rule is enforced both at creation and at submission — a collision is rejected with `ERR_SLOT_OCCUPIED` (HTTP 409). A `GiftOfficer` submits a designation from `DRAFT`, or resubmits one from `REJECTED` (the revise-and-resubmit loop, which clears the stored `rejection_reason`), via the `SUBMIT` action.

Verification and rejection belong to the `GiftAdministrator`. Verifying a `SUBMITTED` designation requires `document_received` to be true — otherwise `ERR_DOCUMENT_NOT_RECEIVED` (HTTP 409) — and moves it to `VERIFIED`; as a side effect, any **other** designation for the same agreement and slot currently in `VERIFIED` flips to `SUPERSEDED`, with its `version` incremented. Rejecting a `SUBMITTED` designation moves it to `REJECTED` and stores the supplied `rejection_reason`. Revocation moves a `VERIFIED` designation to `REVOKED`, but only while the parent agreement's status is `DRAFT` or `EXECUTED` — designation paperwork is frozen once the agreement is funded, and a later attempt fails with `ERR_INVALID_STATE`.

The execution gate of §3.3 depends on this paperwork: an agreement cannot execute until a `VERIFIED` designation occupies the `PRIMARY_1` slot (`ERR_DESIGNATION_NOT_VERIFIED`).

### 3.5. Gift Assets: Receipt, Appraisal, and Liquidation

Contributed assets are tracked as `GiftAsset` resources, addressed by `asset_id`, listed with filters on `gift_agreement_id`, `estate_id`, `asset_kind`, and `status`, and managed by the `EstateManager`. Every asset has exactly one parent: pledging supplies either a `gift_agreement_id` (a lifetime gift against an agreement) or an `estate_id` (a testamentary asset of an estate) — supplying neither or both is rejected with `ERR_ASSET_ORPHAN` (HTTP 422). The pledge records the `asset_kind` — `CASH`, `SECURITIES`, or `REAL_ESTATE` — the `pledged_value_cents` expected value (for `CASH` this **is** the funding value), and an optional free-text `description`. An asset is born `PLEDGED` and moves through `RECEIVED`, optionally `APPRAISED` for real estate, then `LIQUIDATED`, and finally `DISTRIBUTED`; `RETURNED` is the alternative terminal exit.

Receipt moves an asset `PLEDGED` → `RECEIVED`. For securities, the receipt payload must carry `dod_high_price_cents` and `dod_low_price_cents` — the high and low prices on the date of death for an estate asset, or on the receipt date for a lifetime gift — and may additionally carry the alternate-valuation pair `alt_high_price_cents` and `alt_low_price_cents` (estate-linked assets only), captured at six months after the date of death. At receipt the system computes `fmv_cents` for securities as the mean of the selected high/low pair, rounded half-up to whole cents: agreement-linked assets always use the date-of-death pair, while estate-linked assets use the alternate pair once their estate has elected alternate valuation; assets missing the alternate pair keep the date-of-death basis even after the election. `fmv_cents` remains null until receipt.

Every receipt, appraisal, or return recomputes the parent agreement's `received_value_cents`: the sum over linked assets whose status is `RECEIVED`, `APPRAISED`, `LIQUIDATED`, or `DISTRIBUTED`, where a `CASH` asset contributes its `pledged_value_cents`, a `SECURITIES` asset contributes its `fmv_cents`, and a `REAL_ESTATE` asset contributes its `appraised_value_cents` (zero until appraised). At the end of every receipt or appraisal transition on an agreement-linked asset, the system re-evaluates the funding threshold: if the agreement is `EXECUTED`, is not a `BEQUEST` (bequests are unfunded by definition and mature on death), and `received_value_cents` is at least `gift_amount_cents` — an inclusive boundary — the agreement auto-transitions to `FUNDED`, and the reserve fund's booked and projected targets are recomputed (a CGA requirement joins the booked set and leaves the projected-only set).

Appraisal exists only for real estate: appraising supplies `appraised_value_cents` and moves a `RECEIVED` real-estate asset to `APPRAISED`; attempting it on cash or securities is rejected with `ERR_INVALID_STATE`. Liquidation moves an asset from `RECEIVED` or `APPRAISED` to `LIQUIDATED`, with `gross_proceeds_cents` and `liquidation_costs_cents` (defaulting to zero) supplied in the payload; real estate must reach `APPRAISED` before it may be liquidated, else `ERR_ASSET_KIND_REQUIRES_APPRAISAL` (HTTP 409). Liquidation computes the per-asset `net_proceeds_cents` as `gross_proceeds_cents` minus `liquidation_costs_cents` — the pinned per-asset rounding step of §2.6 — and then cascades: if the asset is linked to a `CGA` agreement, the reserve fund's `balance_cents` grows by the net proceeds, after which coverage and posture are recomputed (a deficient fund may flip back to `SOLVENT`); if the asset is estate-linked, the estate's `gross_proceeds_cents` is recomputed instead.

Distribution moves a `LIQUIDATED` asset to `DISTRIBUTED`; an estate-linked asset may only be distributed while its estate is `DISTRIBUTION_PENDING` or `DISTRIBUTED`, else `ERR_INVALID_STATE`. Return moves a `RECEIVED` asset to `RETURNED` and is permitted for agreement-linked assets only while the parent agreement is `EXECUTED` or `RESCINDED` — assets of a funded or active agreement cannot be returned — with the agreement's `received_value_cents` recomputed as the asset leaves the inclusion set.

### 3.6. Annuity Payment Schedules and Servicing

Once an agreement is `FUNDED`, a `GiftAdministrator` generates its payment schedule — a transition to `ACTIVE` that is forbidden for `BEQUEST` vehicles (`ERR_BEQUEST_VEHICLE_MISMATCH`). The schedule's length in payments is the frequency divisor multiplied by the remaining contract years, where the frequency divisor is 1 for `ANNUAL`, 2 for `SEMIANNUAL`, 4 for `QUARTERLY`, and 12 for `MONTHLY`, and the remaining years are 100 minus the oldest annuitant's age, floored at a minimum of 1. The first payment's `due_date` falls exactly one frequency period after the funding date, each subsequent payment advances by one period, and payments are indexed by `period_index` starting at 1. Each payment's `amount_cents` is the agreement's `annual_annuity_cents` divided by the frequency divisor, rounded half-up, with every payment independently rounded and no cumulative true-up (§2.6). The agreement's `total_scheduled_cents` becomes the sum of all created payment amounts, and its `version` increments.

Payments — addressed by `payment_id` and listed with filters on `gift_agreement_id` and `status` — follow the lifecycle `SCHEDULED` → `DUE` → `PAID`, with `DUE` → `DEFERRED` → `DUE` as a deferral loop and `LAPSED` as the absorbing exit. The logical-clock sweep (§2.4) flips `SCHEDULED` payments at or past their `due_date` to `DUE` and `DEFERRED` payments at or past their `defer_until` back to `DUE`; the same sweep applies lazily whenever payments are read.

Disbursing a payment (`PAY`, by a `GiftAdministrator`) requires the payment to be `DUE` — otherwise `ERR_PAYMENT_NOT_DUE` (HTTP 409) — and the parent agreement to be `ACTIVE`: a `SUSPENDED` parent yields `ERR_AGREEMENT_SUSPENDED`, and any other parent status yields `ERR_INVALID_STATE`. (In practice, `MATURED` and `TERMINATED` agreements hold no non-lapsed payments, so the latter is reachable only through crafted states.) Payment stamps `paid_at` from the logical clock, recomputes the parent agreement's `total_paid_cents` as the sum of `amount_cents` over its `PAID` payments, and increments both the payment's and the agreement's `version`.

Deferral (`DEFER`) moves a `DUE` payment to `DEFERRED` with a `defer_until` instant that must lie strictly in the future of the logical clock, else `ERR_INVALID_REQUEST` (HTTP 400). Lapsing is available from `SCHEDULED`, `DUE`, or `DEFERRED`, either directly — where `lapse_reason` is `MANUAL` — or through the cascades of §3.1 and §3.3, which stamp `DONOR_DEATH`, `TERMINATION`, or `MATURITY` according to the triggering event. Every lapse recomputes the parent agreement's `liability_released_cents` (the sum of `amount_cents` over its `LAPSED` payments) and increments both versions. Alongside `total_paid_cents` and `liability_released_cents`, the agreement continuously reports `total_scheduled_cents` as the sum over **all** of its payments regardless of status.

### 3.7. Estates, Probate Milestones, and the Distribution Waterfall

An estate file opens in two ways: automatically through the death cascade of §3.1 when a matured bequest exists, or manually when an `EstateManager` opens a file for a `DECEASED` donor — supplying `donor_id`, the `notified_on` date the office learned of the death, and optionally the related `gift_agreement_id` — with a `LIVING` donor rejected as `ERR_DONOR_STATE_MISMATCH`. The opener's `X-User-ID` is recorded as `recorded_by_user_id` and later anchors the distribution segregation-of-duties check. Estates are filterable in the list by `donor_id`, `gift_agreement_id`, and `status`, and follow the lifecycle `NOTIFIED` → `PROBATE_OPEN` → `DISTRIBUTION_PENDING` → `DISTRIBUTED` → `CLOSED`, with `CONTESTED` as a detour: contesting moves `PROBATE_OPEN` → `CONTESTED`, and resolving the contest returns the estate to `PROBATE_OPEN`.

While an estate is `NOTIFIED` or `PROBATE_OPEN`, the `EstateManager` may make the one-way alternate-valuation election (`ELECT_ALTERNATE_VALUATION`), permitted only while `alternate_valuation_elected` is false. The election changes no status, but flips the valuation basis: every linked securities asset not still `PLEDGED` has its `fmv_cents` recomputed as the mean of its alternate price pair — `alt_high_price_cents` and `alt_low_price_cents` — rounded half-up; assets lacking the alternate pair retain their date-of-death basis. Identical date-of-death inputs therefore yield a different `fmv_cents` after the election.

Court deadlines are tracked as `ProbateMilestone` resources, addressed by `milestone_id`, added to an estate with its `estate_id`, a `kind` of `PETITION`, `NOTICE_TO_CREDITORS`, `INVENTORY`, `APPRAISAL`, `FINAL_ACCOUNTING`, or `COURT_ORDER`, and a `due_date`; the milestone list filters by `estate_id`, `kind`, and `status`. A milestone begins `PENDING`; filing it (action `FILE`, stamping `filed_on` from the logical clock) moves it to `FILED`, including as a late cure from `OVERDUE`; closing moves `FILED` → `CLOSED`. The clock sweep flips any `PENDING` or `FILED` milestone whose `due_date` is strictly before the current clock time to `OVERDUE`.

Beginning distribution is the estate's fiscal climax, performed by an `EstateManager` on a `PROBATE_OPEN` estate with `administration_costs_cents` and `specific_bequests_cents` (amounts paid to other heirs before the charitable residue) supplied in the payload. Four gates apply, in the order of §2.10: the actor must differ from the estate's `recorded_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked milestone must be `CLOSED` (`ERR_MILESTONES_OPEN`, HTTP 409); every linked gift asset must be `LIQUIDATED`, `DISTRIBUTED`, or `RETURNED` (`ERR_ASSETS_NOT_LIQUIDATED`, HTTP 409); and the waterfall must not overflow — `administration_costs_cents` plus `specific_bequests_cents` must not exceed `gross_proceeds_cents`, else `ERR_DISTRIBUTION_OVERFLOW` (HTTP 422). The estate's `gross_proceeds_cents` is the sum of `net_proceeds_cents` over its linked assets in `LIQUIDATED` or `DISTRIBUTED` status (per-asset rounding first, per §2.6). On success the estate stores both supplied cost figures, computes `residual_to_university_cents` as `gross_proceeds_cents` minus `administration_costs_cents` minus `specific_bequests_cents` — an exact subtraction with no rounding drift, conserving the gross exactly across the three buckets — and moves to `DISTRIBUTION_PENDING`. The residual then cascades: if the estate's `gift_agreement_id` is set and that agreement names a `fund_id`, the fund's `balance_cents` grows by the residual, and if that credit lifts a `PROPOSED` fund to at least its `minimum_endowment_cents`, the fund auto-transitions to `ENDOWED` (inclusive boundary); the fund's `version` increments when credited.

Marking the estate distributed (`MARK_DISTRIBUTED`) stamps `distributed_on` from the logical clock and moves `DISTRIBUTION_PENDING` → `DISTRIBUTED`; closing moves `DISTRIBUTED` → `CLOSED`, which is terminal. Closing an estate does **not** settle its linked agreement — a `MATURED` bequest agreement remains `MATURED` until a `FinanceSteward` settles it per §3.3.

### 3.8. Donor-Intent Funds and Stewardship

A `FinanceSteward` establishes a donor-restricted fund with a `name` (for example, "Smith Family Scholarship Fund"), a `restriction_type` drawn from the same five-value intent vocabulary as agreements (`UNRESTRICTED`, `SCHOLARSHIP`, `FACULTY_SUPPORT`, `RESEARCH`, `CAPITAL`), the sourcing `gift_agreement_id` whose remainder will feed the fund, and an optional `minimum_endowment_cents` defaulting to 2500000 cents (twenty-five thousand dollars). A fund is born `PROPOSED` with a zero balance, and at most one non-`CLOSED` fund may exist per agreement — a duplicate is rejected with `ERR_FUND_ALREADY_EXISTS` (HTTP 409). The fund list filters by `gift_agreement_id`, `restriction_type`, and `status`, and each fund is addressable by its `fund_id`.

Funds accrete value from exactly two sources: agreement settlement, which credits `remainder_value_cents`, and estate distribution, which credits `residual_to_university_cents` (§3.7). On **any** credit, if the fund is `PROPOSED` and its `balance_cents` reaches at least `minimum_endowment_cents` — an inclusive boundary — the system auto-transitions it to `ENDOWED`. Beyond that, a `FinanceSteward` drives the lifecycle with `action` values: `ACTIVATE` moves a `PROPOSED` or `ENDOWED` fund to `ACTIVE` and requires the balance to meet the endowment minimum, else `ERR_FUND_MINIMUM_NOT_MET` (HTTP 409); `FREEZE` moves `ACTIVE` → `FROZEN`; `UNFREEZE` returns `FROZEN` → `ACTIVE`; and `CLOSE` moves a `PROPOSED` fund to the terminal `CLOSED` status. Every fund mutation increments its `version`.

### 3.9. Actuarial Revaluation and Reserve Compliance

The CGA reserve requirement itself is computed per agreement at execution, and recomputed at every valuation posting, as follows: the term is 100 minus the oldest annuitant's age (for a single-life contract, `annuitant_1_age`; for joint lives, the older of the two ages), floored at a minimum of 1; the annuity-immediate factor for that term is computed at a fixed discount rate of 600 basis points (6.00%); and `reserve_requirement_cents` is the agreement's `annual_annuity_cents` multiplied by that factor and by a multiplier of 11000 basis points (110%), rounded half-up to whole cents. Non-CGA vehicles always carry a `reserve_requirement_cents` of zero.

A `ComplianceOfficer` revalues the book of business through a `ValuationRun`. Creating a run supplies a fiscal coverage window — `coverage_start` and `coverage_end`, both inclusive, forming a **closed** interval — a `valuation_date` that must lie within that window (a `valuation_date` outside its own coverage window is rejected with `ERR_INVALID_REQUEST`), and optionally `corpus_updates`, a list of entries each pairing an `agreement_id` with a `new_corpus_cents` value to be applied to `CRT_UNITRUST` agreements before revaluation. The run begins in `DRAFT` with the creator's `X-User-ID` recorded as `created_by_user_id`, and is addressable by its `valuation_run_id`.

Posting the run — by a `ComplianceOfficer` who must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`) — requires the run still be `DRAFT` (a re-post is rejected with `ERR_VALUATION_ALREADY_POSTED`, HTTP 409), requires its closed coverage window not to intersect the closed window of any other `POSTED` run — note that sharing even a single boundary date **is** an overlap, unlike the half-open rate-table windows — (`ERR_VALUATION_WINDOW_OVERLAP`, HTTP 409), and requires an `ACTIVE` rate table covering `valuation_date` to exist (`ERR_NO_ACTIVE_RATE_TABLE`, HTTP 422). Posting then executes a four-hop cascade, atomically:

- **Hop 1:** for every agreement with status `FUNDED`, `ACTIVE`, or `SUSPENDED` and a vehicle other than `BEQUEST`, processed in `created_at` ascending order: apply the matching `corpus_updates` entry first when the vehicle is `CRT_UNITRUST` (setting `corpus_value_cents` to `new_corpus_cents`); advance the annuitant ages by the whole years elapsed from `funding_month` to `valuation_date`; recompute the term as 100 minus the oldest advanced age, floored at 1; take the discount rate from the `ACTIVE` table covering `valuation_date`; for `CRT_UNITRUST`, recompute `annual_annuity_cents` as the new corpus multiplied by `payout_rate_bps` and divided by 10000, rounded half-up — unitrust annuities are annually revalued off current corpus, whereas `CGA` and `CRT_ANNUITY` annuities are fixed at funding and never change; recompute `actuarial_liability_cents` as the (possibly new) annual annuity times the annuity-immediate factor at the new term and rate, rounded half-up; recompute `remainder_value_cents` as corpus minus liability floored at zero; and for `CGA` agreements recompute `reserve_requirement_cents` at the advanced age.
- **Hop 2:** for each `CRT_UNITRUST` agreement revalued in hop 1, recompute the `amount_cents` of its `SCHEDULED` payments as the new annual annuity divided by the frequency divisor, rounded half-up — so a corpus update changes all future scheduled payment amounts.
- **Hop 3:** for each such agreement, recompute `total_scheduled_cents` as the sum of its payment amounts.
- **Hop 4:** recompute the reserve fund's booked and projected targets from the new CGA requirements, then coverage and posture.

The run records `agreements_revalued_count` (the number of agreements processed), `total_liability_cents` and `total_remainder_cents` (the sums across revalued agreements), stamps `posted_at` from the logical clock, stores the poster as `posted_by_user_id`, and moves to the terminal `POSTED` status; the run's `version` and every mutated agreement's and payment's `version` increment.

Between valuations, the reserve fund accepts manual adjustments from a `ComplianceOfficer`: the payload carries a `direction` of `CONTRIBUTION` or `WITHDRAWAL`, an `amount_cents`, and the OCC guard `expected_reserve_fund_version` (§2.9). A contribution adds the amount to `balance_cents`; a withdrawal subtracts it, and the withdrawal amount must not exceed `balance_cents`, else `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422). Coverage and posture are recomputed after every adjustment, and the fund's `version` increments on every balance, target, or posture mutation.

## 4. Endpoint Definitions

All endpoints are mounted under the `/giving` prefix. Operations that create a new resource — registering a donor, creating a rate table, illustration, agreement, designation, asset, estate, milestone, fund, or valuation run, booking an illustration into a new agreement, and generating a payment schedule — return `201 Created`. All other operations, including reads, lifecycle transitions, executions, settlements, terminations, adjustments, and the clock set, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/giving/_clock/set_current_utc` | Advance the logical clock; sweeps payment due/defer and milestone overdue transitions | All roles |
| POST | `/giving/donors` | Register a donor | GiftOfficer |
| GET | `/giving/donors` | List donors (filters: `vital_status`, `legacy_society_status`) | All roles |
| GET | `/giving/donors/{donor_id}` | Read one donor (documented total live-computed) | All roles |
| POST | `/giving/donors/{donor_id}/record-death` | Record donor death; fires the maturity cascade | EstateManager |
| POST | `/giving/donors/{donor_id}/legacy-society-transition` | ENROLL / RECOGNIZE / REVOKE legacy society status | GiftOfficer |
| POST | `/giving/rate-tables` | Create a rate table in DRAFT (window overlap checked) | ComplianceOfficer |
| GET | `/giving/rate-tables/{rate_table_id}` | Read one rate table | All roles |
| POST | `/giving/rate-tables/{rate_table_id}/transition` | ACTIVATE (overlap re-checked) or RETIRE | ComplianceOfficer |
| POST | `/giving/illustrations` | Create an illustration; pins the covering ACTIVE rate table; supersedes an OPEN predecessor | GiftOfficer |
| GET | `/giving/illustrations` | List illustrations (filters: `donor_id`, `rate_table_id`, `supersedes_illustration_id`, `status`) | All roles |
| GET | `/giving/illustrations/{illustration_id}` | Read one illustration | All roles |
| POST | `/giving/illustrations/{illustration_id}/book` | Book an OPEN illustration into a new DRAFT agreement | GiftOfficer |
| POST | `/giving/gift-agreements` | Create a DRAFT agreement directly; pins the covering ACTIVE rate table | GiftOfficer |
| GET | `/giving/gift-agreements` | List agreements (filters: `donor_id`, `fund_id`, `illustration_id`, `rate_table_id`, `status`, `vehicle_type`) | All roles |
| GET | `/giving/gift-agreements/{agreement_id}` | Read one agreement with current computed fields | All roles |
| POST | `/giving/gift-agreements/{agreement_id}/amend` | Amend a DRAFT agreement in place (OCC-guarded) | GiftAdministrator |
| POST | `/giving/gift-agreements/{agreement_id}/execute` | Execute a DRAFT agreement through the full gate chain | GiftAdministrator |
| POST | `/giving/gift-agreements/{agreement_id}/transition` | SUSPEND / RESUME (ComplianceOfficer); WITHDRAW / RESCIND (GiftAdministrator) | GiftAdministrator, ComplianceOfficer |
| POST | `/giving/gift-agreements/{agreement_id}/terminate` | Early termination; surrenders value and lapses open payments | GiftAdministrator |
| POST | `/giving/gift-agreements/{agreement_id}/settle` | Settle a MATURED agreement, crediting its fund | FinanceSteward |
| POST | `/giving/gift-agreements/{agreement_id}/generate-payment-schedule` | FUNDED to ACTIVE; creates the full annuity payment schedule | GiftAdministrator |
| POST | `/giving/beneficiary-designations` | Create a designation in DRAFT (slot occupancy enforced) | GiftOfficer |
| GET | `/giving/beneficiary-designations` | List designations (filters: `gift_agreement_id`, `slot`, `status`) | All roles |
| GET | `/giving/beneficiary-designations/{designation_id}` | Read one designation | All roles |
| POST | `/giving/beneficiary-designations/{designation_id}/transition` | SUBMIT (GiftOfficer); VERIFY / REJECT / REVOKE (GiftAdministrator) | GiftOfficer, GiftAdministrator |
| POST | `/giving/gift-assets` | Pledge an asset against an agreement XOR an estate | EstateManager |
| GET | `/giving/gift-assets` | List assets (filters: `gift_agreement_id`, `estate_id`, `asset_kind`, `status`) | All roles |
| GET | `/giving/gift-assets/{asset_id}` | Read one gift asset | All roles |
| POST | `/giving/gift-assets/{asset_id}/transition` | RECEIVE / APPRAISE / LIQUIDATE / RETURN / DISTRIBUTE | EstateManager |
| GET | `/giving/annuity-payments` | List payments (filters: `gift_agreement_id`, `status`); lazy sweep; sorted by period index within an agreement | All roles |
| GET | `/giving/annuity-payments/{payment_id}` | Read one payment (lazy sweep applied) | All roles |
| POST | `/giving/annuity-payments/{payment_id}/transition` | PAY / DEFER / LAPSE | GiftAdministrator |
| GET | `/giving/reserve-fund` | Read the reserve pool: balance, targets, coverage, posture | All roles |
| POST | `/giving/reserve-fund/adjustments` | Manual reserve CONTRIBUTION / WITHDRAWAL (OCC-guarded) | ComplianceOfficer |
| POST | `/giving/estates` | Open an estate file for a DECEASED donor | EstateManager |
| GET | `/giving/estates` | List estates (filters: `donor_id`, `gift_agreement_id`, `status`) | All roles |
| GET | `/giving/estates/{estate_id}` | Read one estate | All roles |
| POST | `/giving/estates/{estate_id}/transition` | OPEN_PROBATE / CONTEST / RESOLVE_CONTEST / ELECT_ALTERNATE_VALUATION / BEGIN_DISTRIBUTION / MARK_DISTRIBUTED / CLOSE | EstateManager |
| POST | `/giving/probate-milestones` | Add a probate milestone to an estate | EstateManager |
| GET | `/giving/probate-milestones` | List milestones (filters: `estate_id`, `kind`, `status`) | All roles |
| GET | `/giving/probate-milestones/{milestone_id}` | Read one milestone | All roles |
| POST | `/giving/probate-milestones/{milestone_id}/transition` | FILE / CLOSE | EstateManager |
| POST | `/giving/funds` | Create a donor-restricted fund (PROPOSED, balance zero) | FinanceSteward |
| GET | `/giving/funds` | List funds (filters: `gift_agreement_id`, `restriction_type`, `status`) | All roles |
| GET | `/giving/funds/{fund_id}` | Read one fund | All roles |
| POST | `/giving/funds/{fund_id}/transition` | ACTIVATE / FREEZE / UNFREEZE / CLOSE | FinanceSteward |
| POST | `/giving/valuation-runs` | Create a DRAFT valuation run (coverage window, valuation date, optional corpus updates) | ComplianceOfficer |
| GET | `/giving/valuation-runs/{valuation_run_id}` | Read one valuation run (totals populated after posting) | All roles |
| POST | `/giving/valuation-runs/{valuation_run_id}/post` | Post a DRAFT run; revalues all in-scope agreements and the reserve | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VALUATION_ALREADY_POSTED` | 409 |
| `ERR_PAYMENT_NOT_DUE` | 409 |
| `ERR_AGREEMENT_SUSPENDED` | 409 |
| `ERR_DONOR_STATE_MISMATCH` | 409 |
| `ERR_REMAINDER_TEST_FAILED` | 422 |
| `ERR_EXHAUSTION_TEST_FAILED` | 422 |
| `ERR_DESIGNATION_NOT_VERIFIED` | 409 |
| `ERR_DOCUMENT_NOT_RECEIVED` | 409 |
| `ERR_BEQUEST_VEHICLE_MISMATCH` | 422 |
| `ERR_PAYOUT_RATE_OUT_OF_RANGE` | 422 |
| `ERR_SLOT_OCCUPIED` | 409 |
| `ERR_LEGACY_SOCIETY_INELIGIBLE` | 422 |
| `ERR_FUND_ALREADY_EXISTS` | 409 |
| `ERR_RATE_WINDOW_OVERLAP` | 409 |
| `ERR_RATE_TABLE_NOT_ACTIVE` | 409 |
| `ERR_VALUATION_WINDOW_OVERLAP` | 409 |
| `ERR_NO_ACTIVE_RATE_TABLE` | 422 |
| `ERR_ASSET_ORPHAN` | 422 |
| `ERR_MILESTONES_OPEN` | 409 |
| `ERR_ASSETS_NOT_LIQUIDATED` | 409 |
| `ERR_ASSET_KIND_REQUIRES_APPRAISAL` | 409 |
| `ERR_RESERVE_DEFICIENT` | 409 |
| `ERR_INSUFFICIENT_RESERVE_BALANCE` | 422 |
| `ERR_DISTRIBUTION_OVERFLOW` | 422 |
| `ERR_FUND_MINIMUM_NOT_MET` | 409 |
