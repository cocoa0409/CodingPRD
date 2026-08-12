# Grain Cooperative Patronage & Member Equity API — Product Requirements Document

## 1. Introduction

A farmer-owned grain cooperative lives or dies by the trust of its members, and that trust is anchored in two books: the delivery ledger that records every bushel a patron hauls to the elevator, and the equity ledger that records what the cooperative owes each patron back. This document specifies the API for the cooperative's patronage and member-equity platform — the system that turns a year of grain deliveries into patronage allocations, splits those allocations between cash and equity, tracks qualified and nonqualified written notices of allocation as first-class certificates, and governs how that equity is eventually revolved, redeemed, transferred at death, or surrendered to the state when a member cannot be found.

The platform serves a cast of cooperative officers — registrars, accountants, treasurers, elevator operators, an external auditor, and the board secretary — alongside the members themselves. Because patronage math is audited and restated, the system computes every fiscal-year allocation twice under deliberately different assumptions (a provisional pass at close and a final pass after audit), pins its rounding order so two honest implementations produce identical cents, and enforces two zero-tolerance conservation invariants so that no amendment, reversal, or redemption ever creates or destroys value silently. Governance is not an afterthought: revolvement windows, estate approvals, special redemptions, allocation amendments, and escheat authorizations all gate on board resolutions passed by seated delegates. All time-sensitive rules read a single logical clock so that eligibility boundaries — holding periods, claim windows, dormancy periods, voting windows — are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API. Domain workflows in §3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. The recognized roles are exactly: `CoopAdmin`, `CoopRegistrar`, `CoopAccountant`, `ExternalAuditor`, `ElevatorOperator`, `CoopTreasurer`, `BoardSecretary`, and `Member`.

If either header is missing, or `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a member compare the resource's member foreign key to `X-User-ID`, and a `Member` role header whose `X-User-ID` does not reference an existing member record is likewise rejected with `ERR_UNAUTHENTICATED`. When `X-User-Role` is `CoopAdmin`, `CoopRegistrar`, `CoopAccountant`, `ExternalAuditor`, `ElevatorOperator`, `CoopTreasurer`, or `BoardSecretary`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

Beyond authentication, each endpoint admits only the roles listed in §4. An authenticated caller whose role is not authorized for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Cooperative's Logical Clock

All time-gated behavior in the system — fiscal-year close eligibility, certificate holding periods, estate claim windows, revolvement windows, voting windows, appointment slots, dormancy aging, and lapse sweeps — reads a single server-side logical clock, never the host wall clock. On boot, the logical clock is set to `2026-05-01T00:00:00Z`, the deterministic earliest instant from which every time-gated rule is evaluated.

A `CoopAdmin` may advance the clock to an arbitrary UTC instant by submitting `to_iso8601` to the clock-setting capability; the response echoes the new logical time as `now_iso8601`. Timestamps written by the system, such as a delivery's `booked_at`, an estate claim's `filed_at`, a certificate's `issued_at`, or a fiscal year's `closed_at`, are always taken from this logical clock.

### 2.5. Common Resource Properties

Every resource in the system — members, districts, delegates, fiscal years, deliveries, allocations, certificates, cycles, resolutions, redemption requests, estate claims, unclaimed-equity lots, and tax forms — carries a standard set of system-managed fields:

- **`id`** (string): a server-minted UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every mutation.
- **`version`** (integer): starts at its initial value on creation and increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Derived-field recomputation is a mutation. When a settlement bumps a member's cumulative retains, when a disbursement reduces a member's equity totals, or when a cycle's redeemed total advances, the owning resource's `updated_at` refreshes and its `version` increments.

### 2.6. Nested Resource Retrieval

Endpoints that address a resource through another resource — a member's deliveries, a district's delegates, a fiscal year's allocations — validate path identifiers strictly from left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any later identifier or any business rule is examined. A request naming a nonexistent `member_id` therefore fails before a nonexistent `delivery_id` is even considered. The path variables used across the API are `member_id`, `district_id`, `delegate_id`, `fy_id`, `delivery_id`, `alloc_id`, `cert_id`, `cycle_id`, `req_id`, `claim_id`, `lot_id`, `res_id`, and `form_id`.

### 2.7. Units, Money, and Rounding Conventions

All monetary amounts in the system are integer cents — never floating-point dollars. Whenever a monetary computation produces a fraction of a cent, the result is rounded half-up to a whole cent. Grain volumes are integer bushels: a delivery's net bushels are computed by rounding down (floor) to a whole bushel. The one exception to integer arithmetic is a member's share of the patronage pool, which is carried at exactly eight decimal places using half-even (banker's) rounding before being applied to the pool.

Percentage-style inputs are decimal fractions: `dockage_pct` on a delivery must lie between 0.00 and 0.30 inclusive, `retained_reserve_pct` on a fiscal year between 0.0 and 0.5 inclusive, and `qualified_payout_pct` between 0 and 1 inclusive. Inputs outside these ranges are rejected with `ERR_FISCAL_BOUNDARY` (HTTP 422), as is any delivery whose `gross_bushels` is not greater than zero.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

A member withdrawal must carry `expected_member_version`, the withdrawing client’s last observed `version` of the member record. If the member's current `version` has advanced since that observation — for instance because a certificate redemption cascaded an equity-balance update onto the member in the interim — the withdrawal is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), forcing the client to re-read the member and re-issue the request against the fresh version.

A fiscal-year final close must carry `expected_fiscal_year_version`, the accountant's last observed `version` of the fiscal year. If the year's version has advanced — say a delivery settlement touched the year since the accountant last read it — the finalize is rejected with `ERR_STALE_FISCAL_YEAR_VERSION` (HTTP 412).

A redemption disbursement must carry `expected_certificate_versions`, the treasurer's last observed versions of the certificates listed on the request. If any listed certificate's `version` has advanced — for example a prior disbursement already drew down its `outstanding_cents` — the disbursement is rejected with `ERR_STALE_CERTIFICATE_VERSION` (HTTP 412), preventing a double payment against the same certificate.

### 2.9. Equity Conservation Invariants

Two compensating invariants are checked at every final close, at every allocation amendment or reversal, and at every disbursement, with zero tolerance for drift.

**Pool conservation.** For each fiscal year in `CLOSED_FINAL`, the sum over all allocations whose status is not `REVERSED` of each allocation's `cash_paid_cents` plus `qualified_equity_issued_cents` plus `nonqualified_allocation_cents` must equal the year's `patronage_pool_cents` exactly. Any reversal or amendment must re-balance the year's allocations so this equality continues to hold to the cent.

**Certificate conservation.** For every equity certificate in any status other than `REVOKED`, the certificate's `outstanding_cents` plus the sum of all disbursements ever made against that certificate must equal its `face_value_cents` exactly. Reissuing a certificate after an amendment, redeeming it in portions, or settling it through an estate never creates or destroys value: the parts always re-sum to the original face value.

### 2.10. Validation Order

Every request is evaluated against a fixed validation cascade, and the order matters because earlier failures mask later ones. The cascade runs as follows:

1. The `X-User-Role` header is present and names one of the declared roles — otherwise `ERR_UNAUTHENTICATED`.
2. The `X-User-ID` header is present, and for the entity-backed `Member` role it references an existing member — otherwise `ERR_UNAUTHENTICATED`.
3. The role is authorized for the endpoint per §4 — otherwise `ERR_FORBIDDEN`.
4. Every path parameter references an existing resource — otherwise `ERR_NOT_FOUND`.
5. On the three OCC-guarded writes (member withdrawal, fiscal-year finalize, redemption disbursement), the supplied expected version matches the current entity version — otherwise the corresponding stale-version error (`ERR_STALE_MEMBER_VERSION`, `ERR_STALE_FISCAL_YEAR_VERSION`, or `ERR_STALE_CERTIFICATE_VERSION`).
6. The resource is in a valid source state for the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409).
7. Compliance gates: the estate claim window has elapsed before probate is recorded, the member is not `DECEASED` when a new delivery is booked, and no listed certificate is `FROZEN` at disbursement — otherwise `ERR_COMPLIANCE_GATE` (HTTP 422). These gates guard delivery booking, redemption submission, redemption disbursement, and probate recording.
8. Temporal windows: the fiscal year is `OPEN` at delivery booking, the revolvement window has been reached before a cycle opens, the office appointment is not in the past at submission, and the voting window has opened before voting begins — otherwise `ERR_TEMPORAL_WINDOW` (HTTP 422). These checks guard delivery booking, cycle opening, redemption submission, and the opening of voting.
9. Referential integrity: each listed certificate belongs to the requesting member, a certificate's allocation year matches the certificate's own year, a resolution's `subject_ref_id` references an existing target, and an appeal's `appeal_of_request_id` points to a `REJECTED` request of the same member — otherwise `ERR_REFERENTIAL` (HTTP 422). These checks guard redemption-request creation, certificate issuance, resolution creation, and appeals.
10. Aggregate constraints: a cycle's budget is not exceeded, an office appointment slot is not double-booked, a district is not seated beyond its delegate cap, and no overlapping `OPEN` cycle exists for the same equity class — otherwise `ERR_CONSTRAINT_VIOLATION` (HTTP 409). These checks guard cycle opening, redemption submission, delegate seating, and disbursement.
11. Fiscal rules: the requested amount does not exceed the outstanding value of the listed certificates, each certificate's `redeemable_at` has been reached, the patronage pool is not over-allocated, and per-unit retain arithmetic is consistent — otherwise `ERR_FISCAL` (HTTP 422). These checks guard redemption-request creation, disbursement, fiscal-year finalization, and delivery settlement.
12. Boundary conditions: `gross_bushels` is greater than zero, `dockage_pct` lies between 0.00 and 0.30 inclusive, `retained_reserve_pct` between 0.0 and 0.50 inclusive, and `qualified_payout_pct` between 0 and 1 inclusive — otherwise `ERR_FISCAL_BOUNDARY`.

Independent of this cascade, any request whose payload is missing a required field or carries a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Membership, Delegate Districts, and Voting Rolls

A `CoopRegistrar` enrolls a new patron by supplying the member's `patron_ref` (an external patron reference unique within the cooperative), `legal_name`, `member_class`, `joined_at`, `delegate_district_id`, and `is_producer_member`. The `member_class` is one of `INDIVIDUAL`, `PARTNERSHIP`, `CORPORATION`, `LLC`, or `ESTATE`. A newly registered member starts in `ACTIVE` status with all equity counters at zero: `capital_share_balance_cents` (outstanding common and preferred share capital, tracked separately from patronage equity), `qualified_equity_cents`, `nonqualified_equity_cents`, `per_unit_retains_cents`, and `total_patronage_volume_bu`. Only bona fide producer-members — those with `is_producer_member` true — accrue patronage; a member's `status` controls both whether the elevator will accept new deliveries for them and whether they may vote. The member's `qualified_equity_cents` is derived from that member's qualified certificates that are redeemable or active, each contributing its face value less any redeemed portion; `nonqualified_equity_cents` aggregates the same way across the member's nonqualified certificates. `per_unit_retains_cents` accumulates the per-unit retains credited to the member's capital, and `total_patronage_volume_bu` is the member's lifetime patron-sourced bushels. The membership roster can be listed with optional `status` and `delegate_district_id` filters.

Voting power flows through delegate districts. A `CoopAdmin` creates a district with a unique `code`, a display `name`, and `max_delegates`, the number of delegates the district elects to the board; a district's `status` is `ACTIVE`, `MERGED`, or `RETIRED`. A `CoopRegistrar` then seats a delegate in a district by supplying the `member_id`, `term_start` (inclusive), and `term_end` (exclusive). The seated member must be an `ACTIVE` producer-member, and the district must not already seat `max_delegates` active delegates — a seating that would exceed the cap is rejected with `ERR_DELEGATE_CAP_REACHED` (HTTP 409). A delegate's `is_seated` flag is computed: it is true exactly when the delegate's term covers the current logical clock and the delegate's member is `ACTIVE`. Delegate rosters may be listed per district, or across the cooperative filtered by `district_id` or `member_id`.

### 3.2. Intake: Booking and Settling Grain Deliveries

An `ElevatorOperator` books each inbound load as a grain delivery, supplying the `member_id`, the `fiscal_year_id` of the year the delivery belongs to, the `commodity`, the `gross_bushels`, the `dockage_pct` (foreign matter and shrink), and `is_patron_sourced`. The commodity is one of `CORN`, `SOYBEAN`, `WHEAT`, `SORGHUM`, or `SUNFLOWER`. Booking requires the member to be `ACTIVE` — a booking for a member who is `DECEASED` fails the compliance gate with `ERR_COMPLIANCE_GATE` — and the fiscal year to be `OPEN`, otherwise the booking is rejected with `ERR_TEMPORAL_WINDOW`. Boundary violations (`gross_bushels` not greater than zero, or `dockage_pct` above 0.30) are rejected with `ERR_FISCAL_BOUNDARY`. A booked delivery records its `booked_at` from the logical clock and starts in `BOOKED` status. Deliveries flagged as non-patron business (`is_patron_sourced` false) are settled normally but are excluded from the patronage pool entirely.

Settlement converts a `BOOKED` delivery to `SETTLED` and is only permitted while the delivery's fiscal year is still `OPEN`. At settle time the system computes the delivery's `net_bushels` — the `gross_bushels` multiplied by one minus the `dockage_pct`, rounded down to a whole bushel — and then the delivery's `per_unit_retain_cents`, the per-unit retain withheld into member capital. The retain rate is fixed per commodity: 8 cents per bushel for `CORN`, 10 for `SOYBEAN`, 6 for `WHEAT`, 7 for `SORGHUM`, and 9 for `SUNFLOWER`. The delivery's retain is its `net_bushels` multiplied by the commodity's rate, rounded half-up to whole cents — and the rounding order is pinned: each delivery's retain is rounded individually at settle time, and only then accumulated into the member's `per_unit_retains_cents`. An audit-report variant that sums unrounded per-delivery amounts across a member-year and rounds once at year-end is recognized for reconciliation reporting but is never written to the member's balance; it routinely differs from the per-delivery total. Settlement also adds the delivery's `net_bushels` to the member's `total_patronage_volume_bu` when the delivery is patron-sourced. A delivery that is already `SETTLED` cannot be settled again — the second attempt is rejected with `ERR_DELIVERY_ALREADY_SETTLED` (HTTP 409). A still-`BOOKED` delivery may instead be cancelled, moving it to `CANCELLED`. Delivery ledgers can be read per member (optionally filtered by `fiscal_year_id` or `status`) or across the cooperative with `member_id`, `fiscal_year_id`, `status`, and `commodity` filters.

### 3.3. Closing the Year and the Patronage Allocation Waterfall

A `CoopAccountant` opens the books for a year by creating a fiscal year with its `year_code` (for example FY2026), `start_date` (inclusive), `end_date` (exclusive), the year's `net_margin_cents`, the board-set `retained_reserve_pct`, and the `qualified_payout_pct`. The year starts in `OPEN` status; its possible statuses are `OPEN`, `CLOSED_PROVISIONAL`, `UNDER_AUDIT`, `CLOSED_FINAL`, and `REOPENED`.

When the year has run its course — the logical clock has reached the year's `end_date` and no delivery in the year remains `BOOKED` (every delivery is `SETTLED` or `CANCELLED`) — the accountant performs the provisional close, moving the year from `OPEN` to `CLOSED_PROVISIONAL`. The provisional close first computes `patronage_pool_cents`: the year's `net_margin_cents` multiplied by one minus the `retained_reserve_pct`, rounded half-up to whole cents. It then computes, for every member with positive patron volume in the year, a patronage allocation. A member's `allocated_volume_bu` is the sum of `net_bushels` across that member's `SETTLED`, patron-sourced deliveries in the year, and the member's `pool_share_ratio` is that volume divided by the total patron volume across all such deliveries in the year, carried at eight decimal places with half-even rounding.

Each member's gross allocation is the pool multiplied by the member's share, rounded half-up to whole cents. A volume tier then modifies the qualified slice: a member whose `allocated_volume_bu` is at least 10000 bushels is tier `T3` and uses a rate modifier of 1.10; at least 1000 bushels (but below 10000) is tier `T2` with a modifier of 1.05; below 1000 is tier `T1` with a modifier of 1.00. The boundary is inclusive on the lower bound — a volume of exactly 1000 bushels classifies as `T2`, and exactly 10000 as `T3` — and the resulting tier is recorded on the allocation as `tier_code`. The allocation's `qualified_allocation_cents` is the gross allocation multiplied by the tier modifier and by the qualified fraction of seventy percent, rounded half-up to whole cents; the remainder of the gross allocation goes to `nonqualified_allocation_cents`, which is equity only and carries no cash component. The cash the member actually receives, `cash_paid_cents`, is the qualified slice multiplied by the year's `qualified_payout_pct`, rounded half-up; the rest of the qualified slice, `qualified_equity_issued_cents`, is issued as qualified equity, so any rounding residual inside the qualified slice lands in equity rather than cash. Finally, because per-member rounding can drift the sum of slices away from the pool, the reconciliation posts any cents lost or gained across all members to the member with the largest allocated volume, breaking ties by the earliest `joined_at`. The pool conservation invariant of §2.9 must hold exactly once this reconciliation is posted.

The provisional close stamps the year's `closed_at`, and spawns one allocation row per qualifying member with `variant` `PROVISIONAL` and `status` `PROVISIONAL`, each tied to its `fiscal_year_id` and `member_id`. It also issues the corresponding equity certificates — one for the member's `qualified_equity_issued_cents` and one for the `nonqualified_allocation_cents` — in `ISSUED` status. Allocations for a year can be listed with `status` and `variant` filters, and across years with `member_id`, `fiscal_year_id`, `status`, and `variant` filters.

While an allocation is still `PROVISIONAL` and its fiscal year is not yet `CLOSED_FINAL`, the accountant may reverse it, supplying a `reason`. Reversal moves the allocation to `REVERSED`, revokes the certificates it produced (they move to `REVOKED` and their `outstanding_cents` is zeroed), and recomputes the member's equity balances.

### 3.4. Audit, Final Close, Reopening, and Patron Tax Forms

After the provisional close, an `ExternalAuditor` moves the year from `CLOSED_PROVISIONAL` to `UNDER_AUDIT`. With audit adjustments in hand, the accountant then finalizes the year, moving it from `UNDER_AUDIT` to `CLOSED_FINAL` — an OCC-guarded write per §2.8 requiring `expected_fiscal_year_version`.

Finalization recomputes every allocation under the `FINAL` variant: the audited `net_margin_cents` replaces the provisional figure, deliveries cancelled after the provisional close are excluded, and the same largest-volume rounding-reconciliation rule is applied. Every allocation must be reviewed before finalization — either a `FINAL` variant row exists for it or its `PROVISIONAL` row is confirmed. Where the `FINAL` computation agrees with the provisional figures, the allocation transitions `PROVISIONAL` → `FINALIZED`. Where it diverges, the allocation transitions `PROVISIONAL` → `AMENDED`: the original certificates are `REVOKED`, a replacement certificate is issued with `replaces_certificate_id` pointing at the revoked one, and the member's tax form is reissued as a corrected form. Finalization also sets the year's `final_audit_locked` flag, transitions every certificate issued by the year's close from `ISSUED` to `ACTIVE`, and issues a patron tax form for every patron whose allocation is greater than zero.

A closed year is not necessarily sealed forever. The `BoardSecretary` may reopen a `CLOSED_FINAL` year by supplying the `resolution_id` of a `PASSED` board resolution of kind `AMEND_ALLOCATION` referencing that year. Reopening moves the year to `REOPENED`, clears `final_audit_locked`, returns all `FINALIZED` allocations for the year to `PROVISIONAL` pending recalculation, and moves the affected tax forms to `VOID` with corrected versions pending. When the accountant finalizes a `REOPENED` year — again with recalculated allocations reviewed — the reissued tax forms are created as `CORRECTED_1099_PATR` forms whose `corrects_form_id` points at the voided row, with `is_corrected` set.

Each patron tax form records its `member_id`, `fiscal_year_id`, and `form_type` — one of `FORM_1099_PATR`, `FORM_1099_DIV`, or `CORRECTED_1099_PATR` — and moves through `DRAFT`, `ISSUED`, `CORRECTED`, and `VOID` statuses, with `issued_at` null until the form is actually issued. Box amounts are computed per member per fiscal year, excluding any allocation whose status is `REVERSED`: `box_1_patronage_dividends_cents` is the sum, over the member's `FINALIZED` and `AMENDED` allocations for the year, of each allocation's `cash_paid_cents` plus its `qualified_equity_issued_cents`; `box_3_per_unit_retains_cents` is the sum of `per_unit_retain_cents` across the member's `SETTLED` deliveries in the year; and `box_5_redemption_cents` is the total of nonqualified equity redeemed for the member during the year — that is, disbursements against certificates whose `equity_class` is `NONQUALIFIED`. `box_4_federal_withheld_cents` is an input carrying backup withholding when no W-9 is on file. The accountant may void an issued form, supplying a `reason`, in preparation for correction. Tax forms can be listed with `member_id`, `fiscal_year_id`, `corrects_form_id`, `form_type`, and `status` filters.

### 3.5. Equity Certificates and the Revolvement Program

Equity certificates are the cooperative's written notices of allocation. Each certificate records its holder `member_id`, the `fiscal_year_id` of issuance, the `allocation_id` that produced it, its `equity_class` (`QUALIFIED` or `NONQUALIFIED`), its `face_value_cents`, and its live `outstanding_cents` — the face value less the sum of redeemed portions, never below zero. A certificate's possible statuses are `ISSUED`, `ACTIVE`, `PARTIALLY_REDEEMED`, `REDEEMED`, `REVOKED`, `ESCHEATED`, and `FROZEN`. When a certificate flips from `ISSUED` to `ACTIVE` at final close, its `redeemable_at` is fixed as its `issued_at` plus the system's `min_holding_years` holding period; no redemption may touch the certificate before that date.

Revolvement is the board-discretion mechanism by which old equity is retired. The `BoardSecretary` plans a cycle by supplying a `cycle_code`, the `equity_class` of the certificate pool the cycle revolves, a `target_year_offset` (how many years after issuance the cycle retires), the redemption window `window_start` (inclusive) and `window_end` (exclusive), the `budget_cap_cents` the board authorizes the cycle to redeem in total, and the `board_resolution_id` of the enabling resolution. The `board_resolution_id` is recorded on the cycle as supplied; because the enabling resolution typically references the cycle in its own `subject_ref_id`, cycle creation does not require the referenced resolution to exist yet — no referential check on `board_resolution_id` runs at creation (per §2.10, which does not list it among the referential targets). A new cycle starts `PLANNED`. Opening it — moving `PLANNED` → `OPEN` — requires a `PASSED` resolution of kind `OPEN_REVOLVEMENT` referencing the cycle, requires that the logical clock has reached `window_start`, and requires that no other `OPEN` cycle for the same equity class has a window overlapping this one; a conflicting cycle is rejected with `ERR_CYCLE_OVERLAP` (HTTP 409). When the cycle opens, it is assigned as the `revolvement_cycle_id` of the eligible certificates queued into it. A cycle closes — `OPEN` → `CLOSED` — once the clock reaches `window_end` or once its running `redeemed_cents` total reaches `budget_cap_cents`; certificates still outstanding remain in the pool for the next cycle. A `PLANNED` cycle may instead be cancelled outright, moving it to `CANCELLED`. Cycles can be listed with `board_resolution_id`, `equity_class`, and `status` filters; certificate ledgers can be listed per member, or across the cooperative with `member_id`, `fiscal_year_id`, `allocation_id`, `revolvement_cycle_id`, `replaces_certificate_id`, `status`, and `equity_class` filters.

### 3.6. Redemption Requests and Disbursement

A member redeems equity by filing a redemption request, supplying the `member_id`, the request `kind` — one of `ESTATE`, `RETIREMENT`, `SPECIAL_HARDSHIP`, or `CYCLE_REDEMPTION` — the `certificate_ids` to draw against, the `requested_amount_cents`, an office `appointment_at` slot for the notarized signature, and, when the request appeals an earlier denial, an `appeal_of_request_id`. Every listed certificate must belong to the requesting member, otherwise the filing is rejected with `ERR_CERTIFICATE_OWNERSHIP` (HTTP 422); an `appeal_of_request_id` that does not point to a `REJECTED` request of the same member is rejected with `ERR_REFERENTIAL`. The requested amount must not exceed the sum of `outstanding_cents` across the listed certificates, otherwise `ERR_FISCAL`; and the appointment must not lie in the past, otherwise `ERR_TEMPORAL_WINDOW`. A new request starts in `PENDING`; its full status set is `PENDING`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `PAID`, `APPEALED`, and `CANCELLED`.

Office appointments use half-open 30-minute windows: a request booked at `appointment_at` occupies the interval from that instant up to — but not including — 30 minutes later, and two requests at the same office conflict only when their intervals overlap. Adjacent appointments, where one ends exactly when the other begins, do not conflict. The conflict check runs at submission and again at disbursement against all requests at the same office in `UNDER_REVIEW` or `APPROVED` status; a conflict is rejected with `ERR_APPOINTMENT_CONFLICT` (HTTP 409).

Submitting a request moves it `PENDING` → `UNDER_REVIEW`. The filer must be a member in `ACTIVE` or `INACTIVE` status, or an estate executor acting for a `DECEASED` member; every listed certificate must be owned by the member and in `ACTIVE` status; and `requested_amount_cents` must be greater than zero. A `PENDING` request may instead be cancelled by the member, moving it to `CANCELLED`.

The board decides each request under review. The `BoardSecretary` records the `decision` together with the `resolution_id` of a `PASSED` board resolution whose kind corresponds to the request's kind — an estate request is backed by `APPROVE_ESTATE`, a retirement request by `APPROVE_RETIREMENT`, and so on — and the request's `resolution_id` and `decided_at` are recorded. Approval is refused with `ERR_CYCLE_BUDGET_EXCEEDED` (HTTP 422) when a `CYCLE_REDEMPTION` would push the cycle's `redeemed_cents` over its `budget_cap_cents`, and the cycle itself must be `OPEN`. An `ESTATE` request additionally requires its estate claim to be in `PROBATED` or `APPROVED` status and the claim's filing window to have elapsed — fewer than `claim_window_days` since `filed_at` is rejected with `ERR_ESTATE_WINDOW_NOT_ELAPSED` (HTTP 422). The fiscal year that issued the affected certificates must be `CLOSED_FINAL`. A rejection moves the request to `REJECTED`, and the member may appeal within 30 days of `decided_at`; appealing moves the original request to `APPEALED` and spawns a fresh request already in `UNDER_REVIEW` with `appeal_of_request_id` linking it to the rejected one. The appeal endpoint's response body carries the original request — the resource addressed by the path — now in `APPEALED` status; the spawned `UNDER_REVIEW` request is persisted and discoverable through the request-listing endpoints (for example by filtering on `appeal_of_request_id`) but is not the body of the appeal response.

Disbursement is the treasurer's act: it moves an `APPROVED` request to `PAID` and draws down the listed certificates. This is the third OCC-guarded write — the request must carry `expected_certificate_versions` per §2.8. No listed certificate may be `FROZEN` (`ERR_CERTIFICATE_FROZEN`, HTTP 422), and the logical clock must have reached each certificate's `redeemable_at` (`ERR_CERTIFICATE_NOT_REDEEMABLE`, HTTP 422). The payout is distributed across the listed certificates pro rata to their outstanding balances. When the requested amount covers the total outstanding, every certificate is paid in full. Otherwise each certificate's partial payment is its `outstanding_cents` multiplied by the requested amount and divided by the total outstanding, rounded down to whole cents; the cents left over by that truncation are then distributed one cent at a time to the certificates in order of `issued_at` ascending, with ties broken by `created_at` ascending — never by certificate id. A certificate paid short of its full outstanding balance moves `ACTIVE` → `PARTIALLY_REDEEMED` with its `outstanding_cents` reduced; paying the remaining balance moves it to `REDEEMED` with `outstanding_cents` zeroed. Paying a certificate's full outstanding balance in one disbursement moves it directly `ACTIVE` → `REDEEMED`. Each drawdown reduces the member's `qualified_equity_cents` or `nonqualified_equity_cents` according to the certificate's class, and for a `CYCLE_REDEMPTION` the cycle's `redeemed_cents` advances by the amount paid. Requests can be listed per member, or across the cooperative with `member_id`, `resolution_id`, `appeal_of_request_id`, `status`, and `kind` filters.

### 3.7. Death, Withdrawal, Expulsion, and Estate Claims

Membership ends in four ways, each with distinct equity handling. A registrar may move an `ACTIVE` member to `INACTIVE` provided the member has no open redemption request; the member's active certificates remain valid, but no new certificates may be issued to the member while inactive. An `INACTIVE` member may be reactivated back to `ACTIVE`, which also releases any certificates frozen by the inactivation back to `ACTIVE`. A member may also withdraw — an OCC-guarded write requiring `expected_member_version` — permitted only while the member is `ACTIVE` with no open redemption request and no open estate claim referencing them; withdrawal moves the member to `WITHDRAWN` and freezes all of the member's `ISSUED` and `ACTIVE` certificates pending a board resolution. Finally, the board may expel a member: the `BoardSecretary` performs the expulsion, which requires a `PASSED` resolution of kind `APPROVE_SPECIAL_REDEMPTION` referencing the member, moves the member to `EXPELLED`, and makes all of the member's certificates immediately redeemable at face value with a cash payout queued.

When a member dies, the registrar records the death, supplying the `date_of_death` — which must not lie in the future — and the `executor_member_id` of the estate executor, who must be an `ACTIVE` member of class `ESTATE`. Recording the death moves the member from `ACTIVE` to `DECEASED`, spawns an estate claim in `FILED` status naming the executor, freezes all of the decedent's `ACTIVE` certificates pending probate, and cancels any open redemption requests with the cancellation reason `ESTATE_TRANSITION`.

An estate claim captures the decedent's `claim_amount_cents` — the total outstanding equity at the moment the claim is filed — along with its `filed_at` timestamp and its `claim_window_days`, which defaults to 90. The claim's possible statuses are `FILED`, `PROBATED`, `APPROVED`, `DENIED`, `DISTRIBUTED`, and `LAPSED`. Once the probate court has closed the estate, the registrar records probate by supplying `probate_completed_at`, moving the claim `FILED` → `PROBATED`; probate may only be recorded once the logical clock has reached `filed_at` plus the claim window, and the boundary is inclusive — a claim exactly 90 days old is decidable. The board then decides the claim: approval requires a `PASSED` resolution of kind `APPROVE_ESTATE` referencing the claim and moves it to `APPROVED`, releasing all of the decedent's `FROZEN` certificates back to `ACTIVE` so they become transferable to the executor; denial moves it to `DENIED`. When every redemption request arising from an approved claim has reached `PAID`, the claim moves automatically to `DISTRIBUTED`. Should a claim sit in `FILED` for more than 365 days, the system lapses it to `LAPSED` — the certificates remain `FROZEN`, and the board may then turn to escheatment. Claims can be listed with `deceased_member_id`, `executor_member_id`, and `status` filters, or per member in either the decedent or executor capacity.

### 3.8. Dormancy Detection and Escheatment

When a member becomes unreachable, the registrar registers an unclaimed-equity lot against the stranded `certificate_id`, naming the `last_known_member_id`, the state-mandated `dormancy_years` (defaulting to 5), and the two-letter `state_code` of the escheat jurisdiction. The lot starts in `DORMANT` with `dormancy_started_at` stamped from the logical clock. Its `escheat_eligible_at` is computed as the dormancy start plus the dormancy period measured in Gregorian-average years of 365.2425 days each — a leap-year-safe measure rather than calendar years — and eligibility is inclusive of the boundary: a lot whose dormancy has run exactly the mandated period is eligible.

The registrar first notifies the member of record, moving the lot `DORMANT` → `NOTIFIED`. From there the lot ages automatically: once the logical clock reaches `escheat_eligible_at`, the lot moves `NOTIFIED` → `ESCHEAT_PENDING`. The treasurer then executes the escheat, supplying the `resolution_id` of a `PASSED` resolution of kind `AUTHORIZE_ESCHEAT` referencing the lot; the lot moves to `ESCHEATED`, the linked certificate moves to `ESCHEATED` as well, and its outstanding value is remitted to the state. If the member resurfaces before escheat, the member may recover the lot — the acting member's identity must equal the lot's `last_known_member_id` — moving it from `NOTIFIED` to `RECOVERED`. Lots can be listed with `certificate_id`, `last_known_member_id`, `status`, and `state_code` filters.

### 3.9. Board Resolutions

Every discretionary act of the cooperative — opening a revolvement cycle, approving an estate, approving a retirement or special redemption, amending an allocation, authorizing an escheat — is gated on a board resolution. The `BoardSecretary` proposes a resolution by supplying its unique `resolution_code`, its `kind` (`OPEN_REVOLVEMENT`, `APPROVE_ESTATE`, `APPROVE_RETIREMENT`, `APPROVE_SPECIAL_REDEMPTION`, `AMEND_ALLOCATION`, or `AUTHORIZE_ESCHEAT`), the `subject_ref_id` of the target entity the resolution acts upon (a cycle, an estate claim, a redemption request, or an allocation — and the reference must exist, otherwise `ERR_REFERENTIAL`), the `quorum_required`, and the voting window `voting_opens_at` and `voting_closes_at`. A proposal starts in `PROPOSED`; the secretary may instead table it, moving it to `TABLED`.

Once the logical clock reaches `voting_opens_at`, the secretary opens voting, moving the resolution `PROPOSED` → `VOTING`; opening early is rejected with `ERR_TEMPORAL_WINDOW`. Votes are recorded one at a time by supplying the voting `delegate_id` and the `vote`, incrementing the resolution's `votes_for` or `votes_against`; only seated delegates (per §3.1's `is_seated` rule) may vote. When the voting window closes — or when every seated delegate has voted — the tally is taken. If the total votes cast fall short of `quorum_required`, tallying is rejected with `ERR_QUORUM_NOT_MET` (HTTP 422). With quorum met, the resolution passes only if `votes_for` exceeds `votes_against`, moving it to `PASSED`; a tie or majority against moves it to `REJECTED`.

## 4. Endpoint Definitions

All endpoints are mounted under the cooperative's API root. Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Query parameters and request payloads are as described in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coop/_clock/set_current_utc` | Set the logical clock (test-driving) | CoopAdmin |
| POST | `/coop/members` | Register a new member | CoopRegistrar |
| GET | `/coop/members/{member_id}` | Get a member | CoopRegistrar, CoopAccountant, CoopTreasurer, BoardSecretary, Member |
| GET | `/coop/members` | List members, optionally filtered | CoopRegistrar, CoopAccountant, CoopTreasurer, BoardSecretary |
| POST | `/coop/members/{member_id}/deactivate` | Move member ACTIVE → INACTIVE | CoopRegistrar |
| POST | `/coop/members/{member_id}/reactivate` | Move member INACTIVE → ACTIVE | CoopRegistrar |
| POST | `/coop/members/{member_id}/record_death` | Move member ACTIVE → DECEASED; spawn estate claim; freeze certificates | CoopRegistrar |
| POST | `/coop/members/{member_id}/withdraw` | Move member ACTIVE → WITHDRAWN (OCC guarded) | Member, CoopRegistrar |
| POST | `/coop/members/{member_id}/expel` | Move member ACTIVE → EXPELLED (requires PASSED APPROVE_SPECIAL_REDEMPTION resolution) | BoardSecretary |
| POST | `/coop/delegate_districts` | Create a delegate district | CoopAdmin |
| GET | `/coop/delegate_districts/{district_id}` | Get district | CoopAdmin, CoopRegistrar, BoardSecretary |
| POST | `/coop/delegate_districts/{district_id}/delegates` | Seat a delegate in a district | CoopRegistrar |
| GET | `/coop/delegate_districts/{district_id}/delegates` | List delegates in a district | CoopRegistrar, BoardSecretary, CoopAdmin |
| POST | `/coop/fiscal_years` | Create a fiscal year | CoopAccountant |
| GET | `/coop/fiscal_years/{fy_id}` | Get fiscal year | CoopAccountant, CoopTreasurer, BoardSecretary, CoopRegistrar |
| POST | `/coop/fiscal_years/{fy_id}/close_provisional` | Close year provisionally; spawn PROVISIONAL allocations and ISSUED certificates | CoopAccountant |
| POST | `/coop/fiscal_years/{fy_id}/begin_audit` | Move CLOSED_PROVISIONAL → UNDER_AUDIT | ExternalAuditor |
| POST | `/coop/fiscal_years/{fy_id}/finalize_close` | Move UNDER_AUDIT or REOPENED → CLOSED_FINAL (OCC guarded) | CoopAccountant |
| POST | `/coop/fiscal_years/{fy_id}/reopen` | Move CLOSED_FINAL → REOPENED (requires PASSED AMEND_ALLOCATION resolution) | BoardSecretary |
| POST | `/coop/deliveries` | Book a grain delivery | ElevatorOperator |
| GET | `/coop/deliveries/{delivery_id}` | Get delivery | ElevatorOperator, CoopAccountant, CoopTreasurer |
| GET | `/coop/members/{member_id}/deliveries` | List deliveries for a member | ElevatorOperator, CoopAccountant, CoopTreasurer, CoopRegistrar, Member |
| POST | `/coop/deliveries/{delivery_id}/settle` | Settle a booked delivery; compute per-unit retain | ElevatorOperator |
| POST | `/coop/deliveries/{delivery_id}/cancel` | Cancel a booked delivery | ElevatorOperator |
| GET | `/coop/allocations/{alloc_id}` | Get a patronage allocation | CoopAccountant, CoopTreasurer, BoardSecretary |
| GET | `/coop/fiscal_years/{fy_id}/allocations` | List allocations for a fiscal year | CoopAccountant, CoopTreasurer, BoardSecretary |
| POST | `/coop/allocations/{alloc_id}/reverse` | Reverse a PROVISIONAL allocation | CoopAccountant |
| GET | `/coop/certificates/{cert_id}` | Get a certificate | CoopTreasurer, CoopAccountant, BoardSecretary, Member |
| GET | `/coop/members/{member_id}/certificates` | List certificates held by a member | CoopTreasurer, CoopAccountant, BoardSecretary, CoopRegistrar, Member |
| GET | `/coop/deliveries` | List deliveries (filtered) | ElevatorOperator, CoopAccountant, CoopTreasurer, CoopRegistrar, BoardSecretary |
| GET | `/coop/delegates/{delegate_id}` | Get a single delegate | CoopRegistrar, BoardSecretary, CoopAdmin |
| GET | `/coop/delegates` | List delegates (filtered) | CoopRegistrar, BoardSecretary, CoopAdmin |
| GET | `/coop/allocations` | List allocations (filtered) | CoopAccountant, CoopTreasurer, BoardSecretary |
| GET | `/coop/certificates` | List certificates (filtered) | CoopTreasurer, CoopAccountant, BoardSecretary, CoopRegistrar |
| GET | `/coop/revolvement_cycles` | List revolvement cycles (filtered) | BoardSecretary, CoopTreasurer, CoopAccountant |
| GET | `/coop/redemption_requests` | List redemption requests (filtered) | CoopTreasurer, BoardSecretary, CoopRegistrar |
| GET | `/coop/estate_claims` | List estate claims (filtered) | CoopRegistrar, BoardSecretary, CoopTreasurer |
| GET | `/coop/unclaimed_lots` | List unclaimed equity lots (filtered) | CoopRegistrar, CoopTreasurer, BoardSecretary |
| GET | `/coop/tax_forms` | List tax forms (filtered) | CoopAccountant, CoopTreasurer, BoardSecretary |
| POST | `/coop/revolvement_cycles` | Plan a new revolvement cycle | BoardSecretary |
| GET | `/coop/revolvement_cycles/{cycle_id}` | Get cycle | BoardSecretary, CoopTreasurer, CoopAccountant |
| POST | `/coop/revolvement_cycles/{cycle_id}/open` | Open a planned cycle | BoardSecretary |
| POST | `/coop/revolvement_cycles/{cycle_id}/close` | Close an open cycle | BoardSecretary |
| POST | `/coop/redemption_requests` | Create a redemption request | Member |
| GET | `/coop/redemption_requests/{req_id}` | Get a redemption request | Member, CoopTreasurer, BoardSecretary, CoopRegistrar |
| GET | `/coop/members/{member_id}/redemption_requests` | List requests for a member | Member, CoopTreasurer, BoardSecretary, CoopRegistrar |
| POST | `/coop/redemption_requests/{req_id}/submit_for_review` | PENDING → UNDER_REVIEW | Member |
| POST | `/coop/redemption_requests/{req_id}/decide` | UNDER_REVIEW → APPROVED or REJECTED (requires PASSED resolution) | BoardSecretary |
| POST | `/coop/redemption_requests/{req_id}/appeal` | REJECTED → APPEALED; spawns fresh UNDER_REVIEW request | Member |
| POST | `/coop/redemption_requests/{req_id}/disburse` | APPROVED → PAID; certificates drawn down (OCC guarded) | CoopTreasurer |
| POST | `/coop/redemption_requests/{req_id}/cancel` | PENDING → CANCELLED | Member |
| GET | `/coop/estate_claims/{claim_id}` | Get estate claim | CoopRegistrar, BoardSecretary, CoopTreasurer, Member |
| GET | `/coop/members/{member_id}/estate_claims` | List estate claims where member is deceased or executor | CoopRegistrar, BoardSecretary, CoopTreasurer, Member |
| POST | `/coop/estate_claims/{claim_id}/record_probate` | FILED → PROBATED | CoopRegistrar |
| POST | `/coop/estate_claims/{claim_id}/decide` | PROBATED → APPROVED or DENIED | BoardSecretary |
| POST | `/coop/unclaimed_lots` | Register a dormancy detection | CoopRegistrar |
| GET | `/coop/unclaimed_lots/{lot_id}` | Get lot | CoopRegistrar, CoopTreasurer, BoardSecretary, Member |
| POST | `/coop/unclaimed_lots/{lot_id}/notify` | DORMANT → NOTIFIED | CoopRegistrar |
| POST | `/coop/unclaimed_lots/{lot_id}/escheat` | ESCHEAT_PENDING → ESCHEATED (requires AUTHORIZE_ESCHEAT resolution) | CoopTreasurer |
| POST | `/coop/unclaimed_lots/{lot_id}/recover` | NOTIFIED → RECOVERED | Member |
| POST | `/coop/board_resolutions` | Propose a resolution | BoardSecretary |
| GET | `/coop/board_resolutions/{res_id}` | Get resolution | BoardSecretary, CoopRegistrar, CoopTreasurer, CoopAccountant |
| POST | `/coop/board_resolutions/{res_id}/open_voting` | PROPOSED → VOTING | BoardSecretary |
| POST | `/coop/board_resolutions/{res_id}/record_vote` | Record a delegate vote; tallies when the window closes | BoardSecretary |
| POST | `/coop/board_resolutions/{res_id}/table` | PROPOSED → TABLED | BoardSecretary |
| GET | `/coop/tax_forms/{form_id}` | Get a tax form | CoopAccountant, CoopTreasurer, Member |
| GET | `/coop/members/{member_id}/tax_forms` | List tax forms for a member | CoopAccountant, CoopTreasurer, Member |
| POST | `/coop/tax_forms/{form_id}/void` | Void an issued tax form (in preparation for correction) | CoopAccountant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_STALE_FISCAL_YEAR_VERSION` | 412 |
| `ERR_STALE_CERTIFICATE_VERSION` | 412 |
| `ERR_COMPLIANCE_GATE` | 422 |
| `ERR_TEMPORAL_WINDOW` | 422 |
| `ERR_REFERENTIAL` | 422 |
| `ERR_CONSTRAINT_VIOLATION` | 409 |
| `ERR_FISCAL` | 422 |
| `ERR_FISCAL_BOUNDARY` | 422 |
| `ERR_DELIVERY_ALREADY_SETTLED` | 409 |
| `ERR_CYCLE_OVERLAP` | 409 |
| `ERR_CYCLE_BUDGET_EXCEEDED` | 422 |
| `ERR_APPOINTMENT_CONFLICT` | 409 |
| `ERR_ESTATE_WINDOW_NOT_ELAPSED` | 422 |
| `ERR_CERTIFICATE_FROZEN` | 422 |
| `ERR_CERTIFICATE_NOT_REDEEMABLE` | 422 |
| `ERR_DELEGATE_CAP_REACHED` | 409 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_CERTIFICATE_OWNERSHIP` | 422 |
