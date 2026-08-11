# Farmland Leasing API — Product Requirements Document

## 1. Introduction

A farm management company sits between two constituencies that rarely meet: farmland owners — many of them absentee, living far from the ground they hold — and the tenant operators who bid for the right to farm it. Every season the company solicits bids on behalf of owners, scores the applicants, papers the winning lease, collects the cash rent, shares input costs where the lease calls for it, settles up after harvest, polices conservation-practice commitments, allocates the cost of tile drainage and other capital improvements, and keeps absentee owners informed through periodic reports that demand acknowledgment. Each of those steps carries money, statutory deadlines, or both, and each is audited: the manager who finalizes a settlement may not be the manager who countersigns it, and the manager who records a payment may not be the one who reverses it.

This document specifies the API through which that entire cycle is operated. It covers three lease archetypes — cash, flex, and share — each with its own rent formula; a weighted bid-scoring model for tenant selection; payment schedules with late fees, waivers, and corrective reversals; yield-share and flex-bonus harvest settlements with a true-up against amounts already billed; conservation compliance tracking with a tenant standing score that can suspend a bad actor mid-season; improvement projects whose unamortized tenant contribution must be reimbursed when a lease ends early; statutory termination-notice deadlines with automatic renewal when they are missed; and owner reporting with escalation for absentee landlords who do not acknowledge. All state that depends on the passage of time is driven by a single logical clock, never by wall-clock time, so that every deadline, grace period, and sweep is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, declaring the caller's role. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); malformed includes an `X-User-Role` value that is not one of the four declared role names and an `X-User-ID` that is present but blank or whitespace-only. A request whose declared role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Where an endpoint additionally requires that the caller own the target resource, a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Four roles exist, spelled exactly as follows: `FarmManager`, `Landlord`, `Tenant`, and `System`.

`FarmManager` is the farm management company's operator and runs nearly the whole workflow: master-data creation, tenant approval and suspension, offering control, bid curation, lease management, cash-rent collection, settlement processing, expense review, compliance enforcement, project execution, landlord reporting, and logical-clock control. When `X-User-Role` is `FarmManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — for example as `paid_recorded_by` on a `PaymentInstallment`, as `finalized_by` on a `HarvestSettlement`, or as `verified_by` on a `ComplianceRecord` — but never compares it to any entity's `id`.

`Landlord` is the farmland owner. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`; ownership checks on any resource that references a `Landlord` compare the resource's foreign-key field to `X-User-ID`. Landlords select winning bids, consent to capital works, serve or withdraw termination notices as the landlord party, dispute settlements as a lease party, and acknowledge owner reports.

`Tenant` is the farm operator. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` compare the resource's foreign-key field to `X-User-ID`. Tenants bid, revise and withdraw their own bids, submit input-cost expenses, submit conservation evidence, serve or withdraw notices as the tenant party, and dispute settlements as a lease party.

`System` is the automation identity behind the logical-clock sweeps — installment opening and lateness, the compliance non-compliance cascade, lease auto-renewal, notice effectiveness, and report escalation flags. When `X-User-Role` is `System`, `X-User-ID` is an opaque identifier not tied to any persisted entity; `System` performs no HTTP calls of its own, and its transitions are triggered exclusively inside the clock-setting endpoint's sweep pipeline.

All `GET` endpoints are shared: `FarmManager`, `Landlord`, and `Tenant` may read any resource.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0; an out-of-range or non-integer `limit` or `offset` fails with `ERR_VALIDATION` (HTTP 400). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is computed as `offset + len(page) < total_count`. Filter query parameters are exact-equality matches, and numeric filters reject non-integer values with `ERR_VALIDATION` (HTTP 400). Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. The installment list is the single exception: it sorts by `due_date` ascending, breaking ties by `created_at` ascending — the same chronological ordering the system uses whenever installments are reported or auto-allocated as a group; a random id is never used for ordering.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries four common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits; `updated_at` is refreshed on every mutation of the resource, including mutations performed by system sweeps. Datetime fields other than `created_at` and `updated_at` serialize at second precision. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource, again including system-driven mutations such as a lease renewal. Two exceptions qualify the refresh-and-increment rule: the landlord ledger's derived balance fields (§2.10) refresh in place without touching the landlord's `version` or `updated_at`, and the report-escalation flag flip performed by the sweep (§3.10) refreshes `updated_at` only, without incrementing `version`. These properties are universal — no entity in this domain omits them.

Path identifiers are validated left to right: every id appearing in a URL path must resolve to an existing resource, and the first id that does not resolve fails the request with `ERR_NOT_FOUND` (HTTP 404). The same rejection applies to foreign-key references carried in a request body — `landlord_id`, `field_id`, `offering_id`, `bid_id`, or `lease_id` values that do not resolve to existing resources — and, when awarding an offering, to a `bid_id` that resolves but does not belong to the offering named in the path.

### 2.5. The Logical Clock and the Sweep Pipeline

All time-dependent behavior in the system — bidding windows, acceptance expiry, installment opening, grace periods, cure deadlines, notice deadlines, renewal, escalation — reads a single logical clock, never wall-clock time. Before any call to the clock-setting capability, the logical clock reads exactly 2026-05-01T00:00:00Z. A `FarmManager` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the clock to that instant; the clock never falls back to wall-clock time on its own. The response reports the resulting `current_utc` and the number of `sweeps_applied`.

Setting the clock runs every due sweep, in this fixed order: first, installments transition from `SCHEDULED` to `OPEN` and from `OPEN` to `LATE`, charging late fees as they go; second, the compliance cure-deadline cascade flips unresolved records to `NON_COMPLIANT`; third, lease auto-renewal runs for leases whose notice deadline has passed; fourth, served termination notices whose effective date has arrived become `EFFECTIVE` and terminate their leases; fifth, owner-report escalation flags are raised for unacknowledged reports. The reported `sweeps_applied` counts primary transitions performed by the sweep, with each entity that advanced state counting once. The sweep runs to a fixpoint: an entity may undergo more than one transition within a single sweep pass when the second transition's precondition is satisfied by the first — for example, an installment that becomes `OPEN` and immediately qualifies as `LATE` in the same pass. Each fired sweep applies the side effects of its own transitions, and each of those side effects is described in the workflow narratives of §3.

### 2.6. Monetary Precision and Rounding Discipline

All money is carried as integer cents; no fractional cents ever persist. Whenever a computation produces a fractional cent, the value is rounded half up to the nearest whole cent, and the rounding happens at the granularity the individual calculation pins — per installment in rent-schedule generation, per expense line in input-cost sharing, per term year in rent escalation, and on the flex bonus before its cap is applied. Where a remainder exists after per-line rounding, it is allocated to the last installment of the term year, never spread across lines. The bid evaluation score is the one non-monetary exception to integer precision: it is rounded half up to four decimal places. Dates that participate in statutory deadlines operate at day granularity.

### 2.7. Optimistic Concurrency Control

Three write operations guard against stale reads with optimistic concurrency control, each naming the parent entity whose `version` the client must prove it has observed.

Amending a lease (`PATCH /leases/{leaseId}`) requires the request to carry `expected_lease_version`, holding the lease `version` the client last observed. Creating a harvest settlement (`POST /settlements`) likewise requires `expected_lease_version`, because a settlement is written against a specific observed state of its lease. Revising a bid (`PATCH /bids/{bidId}`) requires `expected_bid_version`, the bid `version` the client last observed. In all three cases, if the supplied value does not match the parent entity's current `version` — because another write has advanced that version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check is applied per-endpoint at the following points: bid revision checks `expected_bid_version` before applying any field update; lease amendment checks `expected_lease_version` after state validation and before applying any field update; settlement creation checks `expected_lease_version` after validation of the request body and before creating the new settlement. The field is non-optional on these three endpoints. Endpoints not named here take no version field at all.

### 2.8. Validation Pipeline and Check Ordering

Incoming requests are validated against a fixed pipeline, and when several checks would fail, the earliest category's error is the one returned. The order is:

1. Header presence and shape — missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400), on every endpoint.
2. Role authorization — a caller whose role is not authorized for the endpoint yields `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403), on every endpoint.
3. Request-body shape — missing required fields, invalid enum members, non-positive amounts where a positive amount is required, missing conditional bid parameters for the declared `lease_type`, an `escalation_pct` present when it should be absent or vice versa, a `term_end_date` that is not later than `term_start_date`, a `conservation_practices` amendment attempted while the lease is `ACTIVE`, or a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400), on every endpoint that takes a body.
4. Existence — unresolvable path ids or body foreign keys yield `ERR_NOT_FOUND` (HTTP 404), including an award `bid_id` that does not belong to the path offering. The award endpoint is an exception to this global category order: it performs the ownership check on the offering (category 5) before resolving the request-body `bid_id` to an existing bid.
5. Ownership — entity-backed callers who do not own the target yield `ERR_NOT_RESOURCE_OWNER` (HTTP 403): a `Tenant` revising or withdrawing a bid, submitting an expense, submitting compliance evidence, or disputing a settlement must be the bid's owner or the lease's tenant; a `Landlord` awarding an offering, approving or rejecting an improvement, acknowledging a report, or disputing a settlement must own the field, the report, or the lease; a notice's creator or withdrawer must be the serving party.
6. State preconditions — the target resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409); settlement creation requires the lease to be `ACTIVE`, `TERMINATION_PENDING`, or `TERMINATED` and expense creation requires the lease to be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`, HTTP 409); bid creation and lease activation require the tenant to be `APPROVED` (`ERR_TENANT_NOT_APPROVED`, HTTP 409). `ERR_PRICE_NOT_FINAL` (HTTP 409) is also a state-category error, evaluated immediately after the settlement's `PROVISIONAL`-state check on finalization.
7. Compliance and duty gates — lease activation is blocked while the tenant holds any `NON_COMPLIANT` compliance record on any lease (`ERR_TENANT_NONCOMPLIANT`, HTTP 409); settlement countersigning requires a countersigner different from `finalized_by` and payment reversal requires a reverser different from `paid_recorded_by` (`ERR_DUTY_SEGREGATION_VIOLATION`, HTTP 403).
8. Deadline and window checks — bid creation after the offering's `bid_deadline` yields `ERR_BID_WINDOW_CLOSED` (HTTP 409); lease creation more than thirty days after the bid's `accepted_at` yields `ERR_BID_ACCEPTANCE_EXPIRED` (HTTP 409); a report whose `period_start` is later than its `period_end` yields `ERR_INVALID_PERIOD` (HTTP 422).
9. Type applicability — settlement creation on a `CASH` lease yields `ERR_SETTLEMENT_NOT_APPLICABLE` (HTTP 409); an expense record on a `CASH` lease, which has no input-cost sharing, yields `ERR_INPUT_SHARING_NOT_APPLICABLE` (HTTP 409); an improvement whose `landlord_share_pct` and `tenant_share_pct` do not sum to exactly 1.0 yields `ERR_COST_SHARE_INVALID` (HTTP 422).
10. Cross-entity referential integrity — an overlapping `ACTIVE` or `TERMINATION_PENDING` lease on the same field yields `ERR_FIELD_LEASE_OVERLAP` (HTTP 409); an overlapping report period for the same landlord yields `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409); a bid already linked to a lease originating a second lease yields `ERR_BID_ALREADY_LEASED` (HTTP 409); a `FINALIZED`, `DISPUTED`, or `COUNTERSIGNED` settlement already existing for the same lease and crop year yields `ERR_SETTLEMENT_YEAR_FINAL_EXISTS` (HTTP 409).
11. Money caps and amounts — a `cash_equivalent_bid_cents_per_acre` below the offering's `min_bid_per_acre_cents` yields `ERR_BID_BELOW_MINIMUM` (HTTP 409); a payment exceeding the outstanding balance yields `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 409); a waiver above the manager's authority without landlord consent yields `ERR_WAIVER_EXCEEDS_AUTHORITY` (HTTP 409).

### 2.9. Lease Terms, Statutory Notice, and Interval Semantics

A lease term is a half-open interval: it includes `term_start_date` and excludes `term_end_date`, written `[term_start_date, term_end_date)`. Overlap between leases on the same field is judged under these half-open semantics, so two leases whose terms merely touch — one ending exactly when the other begins — are adjacent, not overlapping, and are allowed. Owner-report windows follow the opposite convention: the period is the closed interval `[period_start, period_end]` with both ends inclusive, and two reports for the same landlord whose windows share even a single endpoint overlap.

Every lease carries a statutory notice lead time, `notice_lead_days`, defaulting to 180 days. The lease's `current_notice_deadline` is its `term_end_date` minus that lead time, recomputed on every renewal. A termination notice served on or before the deadline is on time and takes effect at the current term's end; a notice served after it misses the statutory window and takes effect at the end of the following term instead. The boundary is inclusive on the on-time side: service exactly on the deadline counts as on time. Renewal, conversely, is strict: the auto-renewal sweep renews a lease only when the clock is strictly later than `current_notice_deadline`, so a clock reading exactly equal to the deadline does not renew, and a notice served exactly on the deadline blocks renewal.

### 2.10. Landlord Ledger Principles

Each landlord carries two derived balances, recomputed immediately on every triggering mutation — installment creation, payment, reversal, waiver, the `SCHEDULED`-to-`OPEN` and `OPEN`-to-`LATE` transitions, lease termination, and settlement countersigning. The `total_received_cents` balance is the sum of `paid_cents` over all installments of all leases belonging to that landlord, regardless of installment status. The `pending_receivable_cents` balance is the sum, over installments of that landlord's leases currently in `OPEN` or `LATE` status, of each installment's scheduled `amount_cents` plus its `late_fee_cents` minus its `paid_cents`. Consistency is immediate: no triggering mutation completes without the balances reflecting it.

### 2.11. Segregation of Duties Among Managers

Two compensating or confirming actions are forbidden to the manager who performed the original. A harvest settlement finalized by one manager must be countersigned by a different manager: the countersigning request's `X-User-ID` must differ from the settlement's `finalized_by`, or it is rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403). A payment recorded by one manager must be reversed by a different manager: the reversal request's `X-User-ID` must differ from the installment's `paid_recorded_by`, under the same error and status. Both checks exist so that no single operator can both commit and conceal a financial movement.

## 3. Business Logic & Workflows

### 3.1. Onboarding Landlords, Tenants, and Fields

A `FarmManager` begins by registering each farm owner. Creating a landlord requires a `name` and a `contact_email`; three optional attributes govern owner communication. The `absentee` flag, defaulting to false, marks owners who are not involved day to day and drives report-acknowledgment escalation. The `report_channel`, one of `EMAIL`, `MAIL`, or `PORTAL` and defaulting to `EMAIL`, records the owner's preferred delivery channel. The `ack_required_days` value, a positive integer defaulting to 14, is the number of days an absentee owner has to acknowledge a report before escalation is required. Each landlord's two ledger balances, `total_received_cents` and `pending_receivable_cents`, start at zero and are maintained thereafter per the ledger principles of §2.10. The landlord directory can be listed with an optional `absentee` filter; the filter accepts the string values "true"/"1" and "false"/"0" case-insensitively, and any other value applies no filter.

Tenant operators are registered with a `name` and their `years_experience`, a non-negative integer that later feeds bid scoring. A new tenant starts in `APPLICANT` status with a `compliance_score` of 100, on a scale that runs from 0 to 100. Approval by a manager moves an applicant from `APPLICANT` to `APPROVED`, and only `APPROVED` tenants may bid or have leases activated for them; approving a tenant who is already `APPROVED` fails with `ERR_INVALID_STATE` (HTTP 409). Suspension — by a manager's explicit action, or automatically by the compliance cascade described in §3.6 — moves an `APPROVED` tenant to `SUSPENDED` and ripples outward: every bid of that tenant still in `SUBMITTED` or `SHORTLISTED` status transitions to `WITHDRAWN`, and each affected offering recomputes its `eligible_bid_count` and re-runs evaluation scoring over its remaining eligible bids. Suspending a tenant who is not currently `APPROVED` fails with `ERR_INVALID_STATE` (HTTP 409). Reinstatement is manual: the same approval action moves `SUSPENDED` back to `APPROVED`, but bids withdrawn by the cascade stay `WITHDRAWN`. The tenant list accepts an optional `status` filter.

Fields are the leasable ground. A manager creates one for a landlord by supplying the owning `landlord_id`, a `name`, the tillable `acres` as a positive integer, and the `soil_csr2` productivity rating on the 0-to-100 CSR2 scale — `soil_csr2` accepts any JSON number, integer or float, in the closed range [0, 100]; the optional `drainage_status`, one of `POOR`, `ADEQUATE`, or `TILED`, defaults to `ADEQUATE`. A field's `status` starts at `AVAILABLE`, becomes `LEASED` while any lease on it is `ACTIVE` or `TERMINATION_PENDING`, and returns to `AVAILABLE` when the last such lease terminates. The field list accepts optional `landlord_id` and `status` filters.

### 3.2. Offering a Field and Running the Bidding Window

To solicit tenants, a manager opens a lease offering on a field. The creation payload names the `field_id` and sets the commercial frame: `term_years` between 1 and 5, the proposed `term_start_date`, a `min_bid_per_acre_cents` floor of zero or more, and the `bid_deadline` after which bids stop being accepted. Two reference agronomic figures, `reference_yield_bu_per_acre` and `reference_price_cents_per_bu` — both positive — are recorded on the offering for use in scoring estimates. An offering opens in `OPEN` status with an `eligible_bid_count` of zero; that count always reflects the number of the offering's bids currently in `SUBMITTED` or `SHORTLISTED` status and is recomputed on every bid creation, revision, withdrawal, award, cancellation, and tenant-suspension cascade. The offering list accepts optional `field_id` and `status` filters.

A tenant bids by submitting a payload containing the target `offering_id` and a declared `lease_type` of `CASH`, `FLEX`, or `SHARE`; the bid's `tenant_id` is taken from the caller's `X-User-ID`, never from the body, and an `X-User-ID` that does not resolve to an existing tenant entity fails with `ERR_NOT_FOUND` (HTTP 404). The remaining amount parameters are conditional on the declared type, and a missing conditional parameter is a body-shape failure under §2.8. A `CASH` bid requires `cash_bid_per_acre_cents`, the fixed per-acre cash offer. A `FLEX` bid requires `flex_base_per_acre_cents` (the guaranteed base per acre), `flex_bonus_pct` (the landlord's bonus share of revenue above the trigger, between 0 and 1), `flex_cap_cents` (the annual bonus cap), and `revenue_trigger_cents` (the gross revenue above which the bonus applies). A `SHARE` bid requires `landlord_share_pct` (the landlord's share of gross revenue, between 0 and 1) and `input_share_pct` (the landlord's share of approved input costs, between 0 and 1); `input_share_pct` is optional on a `FLEX` bid. Regardless of type, `cash_equivalent_bid_cents_per_acre` is always required — the tenant's stated cash-equivalent offer per acre, which feeds both the evaluation score and the minimum-bid check.

Four guards protect the bidding act. The tenant must be `APPROVED`, else `ERR_TENANT_NOT_APPROVED`. The offering must still be `OPEN`, else `ERR_INVALID_STATE`. The clock must be on or before the offering's `bid_deadline`; a bid arriving after the deadline is rejected with `ERR_BID_WINDOW_CLOSED`. And the `cash_equivalent_bid_cents_per_acre` must be at least the offering's `min_bid_per_acre_cents`, else `ERR_BID_BELOW_MINIMUM`. A bid that passes starts in `SUBMITTED` status, its `evaluation_score` is computed, and the offering's `eligible_bid_count` is recomputed.

While a bid remains `SUBMITTED`, its tenant may revise any of its amount parameters — the per-type amounts and the `cash_equivalent_bid_cents_per_acre` — through a revision request that must carry `expected_bid_version` per the optimistic-concurrency rule of §2.7, with the minimum-bid check applied to the revised figures. Each accepted revision increments the bid's `version` and recomputes the evaluation scores of all eligible bids on the offering. A revision rejected by the minimum-bid check still persists the submitted amount fields on the bid record, but does not increment `version` or refresh `updated_at`. A tenant may also withdraw a bid they own — the bid's `tenant_id` must equal the caller's `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` — moving it from `SUBMITTED` or `SHORTLISTED` to `WITHDRAWN`; the same withdrawal happens automatically to all of a tenant's live bids when the tenant is suspended, and that system cascade is exempt from the ownership check.

Curation belongs to managers. Shortlisting moves a bid from `SUBMITTED` to `SHORTLISTED` and requires the offering to still be `OPEN`, failing with `ERR_INVALID_STATE` once it is not; demoting returns a `SHORTLISTED` bid to `SUBMITTED`. Both actions recompute the offering's `eligible_bid_count` and evaluation scores. The bid list accepts optional `offering_id`, `tenant_id`, and `status` filters.

### 3.3. Tenant Selection: Scoring, Closing, and Award

Every eligible bid — one in `SUBMITTED` or `SHORTLISTED` status on the offering — carries an `evaluation_score` rounded half up to four decimal places, computed from three weighted components. The rent component is the bid's `cash_equivalent_bid_cents_per_acre` divided by the highest such value among the offering's eligible bids; a bid that is alone in the pool scores a rent component of exactly 1.0, and when the pool's maximum cash-equivalent rent component is zero — all eligible bids offered zero — the top-scored bids, those whose component equals the maximum, receive a rent component of 1.0 and all others 0. The compliance component is the bidding tenant's `compliance_score` divided by 100. The experience component is the tenant's `years_experience`, capped at twenty years, divided by 20 — so twenty or more years of experience saturates the component. The score itself is the sum of the rent component weighted at 0.6, the compliance component weighted at 0.25, and the experience component weighted at 0.15. When managers review candidates, the recommendation order is the score in descending order, ties broken by the bid's `created_at` in ascending order — never by a random id. Scores are recomputed for all eligible bids of an offering whenever any bid is created, revised, withdrawn, shortlisted, demoted, awarded, or caught in a tenant-suspension cascade.

Closing the window is a manager action that moves an `OPEN` offering to `CLOSED`, after which no further bidding or shortlisting occurs; closing an offering that is not currently `OPEN` fails with `ERR_INVALID_STATE` (HTTP 409). Bids also stop being accepted once the clock passes the `bid_deadline` even without a manual close. Cancellation is available to managers from either `OPEN` or `CLOSED` and moves the offering to `CANCELLED`, a terminal state: every bid of the offering still in `SUBMITTED` or `SHORTLISTED` transitions to `REJECTED`, and the `eligible_bid_count` is recomputed to zero.

Awarding is the owner-only act of tenant selection — managers shortlist, but only the landlord awards. Four guards protect it, evaluated in this order: first, the caller's `X-User-ID` must equal the `landlord_id` of the offering's field, else `ERR_NOT_RESOURCE_OWNER`; second, the request's `bid_id` must reference a bid belonging to this offering, else `ERR_NOT_FOUND`; third, the offering must be `CLOSED`, else `ERR_INVALID_STATE`; and fourth, the bid must be `SHORTLISTED`, else `ERR_INVALID_STATE`. A successful award moves the offering from `CLOSED` to the terminal `AWARDED` state, transitions the winning bid from `SHORTLISTED` to `ACCEPTED` with `accepted_at` stamped from the clock, and transitions every other bid of the offering still in `SUBMITTED` or `SHORTLISTED` to `REJECTED`, with the `eligible_bid_count` recomputed to zero. The thirty days following `accepted_at` are the window in which a lease may be created from the award.

### 3.4. Drafting, Amending, and Activating a Lease

A manager drafts a lease from an awarded bid by supplying the `bid_id`, the `term_start_date` and `term_end_date`, the `payment_pattern`, and the escalation and notice terms. The end date must be later than the start date, else `ERR_VALIDATION`. The bid must be `ACCEPTED`, the clock must be on or before the bid's `accepted_at` plus thirty days — a later attempt fails with `ERR_BID_ACCEPTANCE_EXPIRED` — and a bid already linked to an existing lease cannot originate a second one, failing with `ERR_BID_ALREADY_LEASED`. The field-overlap guard also runs at creation: if another lease on the same field is `ACTIVE` or `TERMINATION_PENDING` and its half-open term interval intersects the new one, creation fails with `ERR_FIELD_LEASE_OVERLAP`.

The new lease copies its commercial identity from the bid and its chain of ownership: `field_id` from the offering, `landlord_id` from the field, `tenant_id` and `lease_type` from the bid. The `base_rent_cents_per_acre` is the bid's `cash_bid_per_acre_cents` for a `CASH` lease, the bid's `flex_base_per_acre_cents` for a `FLEX` lease, and zero for a `SHARE` lease. A `FLEX` lease additionally copies `revenue_trigger_cents`, `flex_cap_cents`, and the bonus percentage into its `landlord_bonus_pct`; a `SHARE` lease copies `landlord_share_pct`; and `input_share_pct` is copied where the bid carries it — required on `SHARE`, optional on `FLEX`, and null on `CASH`. The draft's `term_index` starts at 1, its `landlord_credit_cents` at zero, and its `status` at `DRAFT`.

Payment and escalation terms are chosen at drafting. The `payment_pattern` is one of `MAR_NOV_50_50`, `QUARTERLY`, `FULL_MAR`, or `NONE`, the last being typical for `SHARE` leases where rent is settled against harvest rather than billed on a schedule. The `escalation_type` is `NONE` — the default — or `FIXED_PCT`; an `escalation_pct` between 0 and 0.25 inclusive is required if and only if the type is `FIXED_PCT`, and any mismatch between the two is an `ERR_VALIDATION` failure. The `notice_lead_days` default to 180 and must be positive; the lease's `current_notice_deadline` is computed as `term_end_date` minus that lead. The draft may also carry `conservation_practices`, an array of entries each pairing a `practice_type` of `COVER_CROP`, `NO_TILL`, `BUFFER_STRIP`, or `NUTRIENT_PLAN` with a `due_date`; these obligations become tracked records at activation. The lease list accepts optional `field_id`, `landlord_id`, `tenant_id`, `bid_id`, and `status` filters.

Amendment is deliberately narrow. A manager amends a lease through a request that must carry `expected_lease_version` per §2.7. Amendment is available from `DRAFT` or `ACTIVE`; an amendment attempted in any other state fails with `ERR_INVALID_STATE` (HTTP 409). While the lease is `ACTIVE`, only `base_rent_cents_per_acre`, `escalation_type`, `escalation_pct`, and `notice_lead_days` may change; `conservation_practices` is editable only while the lease is `DRAFT`, and attempting to patch it on an active lease is an `ERR_VALIDATION` failure. After an amendment, the escalation invariant — `escalation_pct` required if and only if `escalation_type` is `FIXED_PCT` — is enforced on the post-patch combination, and amending `notice_lead_days` recomputes `current_notice_deadline` from the new lead time. Amendments never retroactively alter installments that already exist; they apply to future renewals and settlements. Every accepted amendment increments the lease's `version` by one. A draft that will not proceed can be cancelled, moving it from `DRAFT` to the terminal `CANCELLED` state.

Activation is the gate that puts the lease on the ground, and its three preconditions are evaluated in this order: first, the tenant must be `APPROVED`, else `ERR_TENANT_NOT_APPROVED`; second, the tenant must hold no compliance record in `NON_COMPLIANT` status on any lease, else `ERR_TENANT_NONCOMPLIANT`; third, no other lease on the same field may overlap the new term in `ACTIVE` or `TERMINATION_PENDING` status — overlap is judged on the half-open interval `[term_start_date, term_end_date)`, so back-to-back terms that merely touch are allowed — else `ERR_FIELD_LEASE_OVERLAP`. A successful activation moves the lease from `DRAFT` to `ACTIVE`, moves the field from `AVAILABLE` to `LEASED`, generates the payment schedule described in §3.5, and creates one `PENDING` compliance record per entry in `conservation_practices`, each record copying its `practice_type` and `due_date` from the lease entry.

### 3.5. Rent Schedules and Cash Collection

Schedule generation runs at activation and again at every renewal, and each run covers only the lease's current term year rather than every twelve-month term year within the half-open term interval. The annual rent is the lease's `base_rent_cents_per_acre` multiplied by the field's `acres`. Installments are created according to the `payment_pattern`. Under `MAR_NOV_50_50`, two installments fall due on March 1 and November 1 of the term year: the first is half the annual rent rounded half up to whole cents, and the second is the annual rent minus the first. Under `QUARTERLY`, four installments fall due on March 1, June 1, September 1, and December 1: each of the first three is one quarter of the annual rent rounded half up, and the fourth is the annual rent minus three times that rounded quarter. Under `FULL_MAR`, a single installment for the full annual rent falls due on March 1. Under `NONE`, no installments are generated at all. The rounding order is pinned: each installment is rounded half up first, and any remainder is allocated to the last installment of the term year. Installment due dates are stored at 00:00:00 UTC on the named calendar date in the calendar year of the term-year start. Each new installment records its `lease_id` and the `term_index` it bills, starts in `SCHEDULED` status with `late_fee_cents` and `paid_cents` at zero, and has no `last_payment_at` until the first payment arrives.

Two clock sweeps age the schedule. When the clock reaches thirty days before an installment's `due_date`, the sweep moves the installment from `SCHEDULED` to `OPEN` and recomputes the landlord's receivable balance. When the clock passes more than ten days beyond the `due_date` and the amount paid so far does not yet cover the scheduled amount plus the late fee, the sweep moves the installment from `OPEN` to `LATE`; that transition charges the late fee exactly once — five percent of the installment's `amount_cents`, rounded half up to whole cents — and again recomputes the landlord's balances.

Payments are recorded by managers against `OPEN` or `LATE` installments. The request carries an `amount_cents` that must be positive and no greater than the outstanding balance — the scheduled amount plus the late fee minus what has already been paid — or the recording is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. Each payment is allocated as a waterfall: the late-fee portion is covered first, and only then does money flow to principal. The installment's `paid_cents` grows by the amount recorded, `last_payment_at` is stamped from the clock, and `paid_recorded_by` captures the recording manager's `X-User-ID`. The installment reaches `PAID` exactly when its `paid_cents` covers the scheduled amount plus the late fee — equality pays in full — and every recording recomputes the landlord's `total_received_cents` and `pending_receivable_cents`. Partial payments are ordinary; several recordings may precede full coverage.

Reversal is the compensating action, and `PAID` is therefore not a terminal state. A manager other than the one named in `paid_recorded_by` may reverse a `PAID` installment — the segregation-of-duties rule of §2.11, enforced as `ERR_DUTY_SEGREGATION_VIOLATION`. Reversal undoes all payments on the installment in full: `paid_cents` resets to zero, `paid_recorded_by` is cleared, `last_payment_at` is retained rather than cleared, and the installment reopens to `OPEN` — unless the clock has already passed more than ten days beyond the `due_date`, in which case it lands in `LATE` instead, retaining the previously charged `late_fee_cents`. Landlord balances are recomputed either way.

Waiver writes off an outstanding balance, moving an `OPEN` or `LATE` installment to the terminal `WAIVED` state; the request must carry a `reason` that is a non-empty string, but the reason is validated only and is not persisted on the installment record. A manager's unilateral authority extends only to outstanding balances of one hundred thousand cents or less; waiving more than that requires the request to carry `landlord_consent` set to true, and without it the waiver is rejected with `ERR_WAIVER_EXCEEDS_AUTHORITY`. The landlord's receivable balance is recomputed on every waiver. The installment list accepts optional `lease_id` and `status` filters and, per §2.3, sorts by due date and then creation time.

### 3.6. Input-Cost Sharing and Harvest Settlement

`FLEX` and `SHARE` leases share input costs between tenant and landlord. A tenant submits an expense by naming the `lease_id`, a `category` of `SEED`, `FERTILIZER`, `CHEMICAL`, `FUEL`, or `OTHER`, the full invoice `total_cost_cents` as a positive integer, the `incurred_date`, and the `crop_year` the cost applies to. The caller must be the lease's tenant — a mismatch is `ERR_NOT_RESOURCE_OWNER` — and the lease must be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`; an attempt on a `CASH` lease, which has no input sharing, is rejected with `ERR_INPUT_SHARING_NOT_APPLICABLE`. The record starts `SUBMITTED`, copies `landlord_share_pct` from the lease at creation — zero when the lease carries none — and computes its `landlord_share_cents` as the total cost multiplied by that percentage, rounded half up to whole cents per line and pinned at that value. Managers then review: approval moves the record to `APPROVED` and stamps `approved_at` from the clock; rejection moves it to `REJECTED`. Both are terminal. The expense list accepts optional `lease_id`, `status`, and `crop_year` filters.

Settlement is how `FLEX` and `SHARE` leases square the season's rent against the harvest. A manager creates a settlement by naming the `lease_id` and `crop_year` — the crop year maps to the lease term whose `term_start_date` year equals it — together with a `price_source` of `ESTIMATED` or `ACTUAL`, a positive `yield_bu_per_acre`, and a positive `harvest_price_cents_per_bu`. Creation requires the lease to be `ACTIVE`, `TERMINATION_PENDING`, or `TERMINATED`, else `ERR_LEASE_NOT_ACTIVE`; a `CASH` lease is rejected with `ERR_SETTLEMENT_NOT_APPLICABLE`; and the request must carry `expected_lease_version` per §2.7, so a client that has not observed the lease's latest version is rejected with `ERR_STALE_VERSION`. Only one non-`VOID` settlement may exist for a lease and crop year: an existing sibling in `FINALIZED`, `DISPUTED`, or `COUNTERSIGNED` blocks creation with `ERR_SETTLEMENT_YEAR_FINAL_EXISTS`, while an existing `PROVISIONAL` sibling is superseded to `VOID` by the newcomer. Creation increments the lease's `version` by one.

The computed amounts begin with `gross_revenue_cents`, the yield per acre multiplied by the price per bushel multiplied by the field's `acres`. For a `FLEX` lease, the base total is the lease's `base_rent_cents_per_acre` multiplied by the field's `acres`, and a bonus applies only when gross revenue strictly exceeds the lease's `revenue_trigger_cents` — at exact equality there is no bonus. The raw bonus is the excess of gross revenue over the trigger, multiplied by the lease's `landlord_bonus_pct`; the charged bonus is zero when that raw value is not positive, and otherwise the smaller of the lease's `flex_cap_cents` and the raw bonus rounded half up to whole cents, the rounding applied before the cap. The `landlord_amount_cents` is the base total plus the bonus. For a `SHARE` lease, the `landlord_amount_cents` is simply the gross revenue multiplied by the lease's `landlord_share_pct`, rounded half up to whole cents.

Input sharing then reduces the landlord's take. The `input_share_total_cents` is the sum of the `landlord_share_cents` over the lease's expense records for the same `crop_year` that are in `APPROVED` status — submitted or rejected expenses are excluded — with each line rounded half up to whole cents first and the rounded lines then summed; summing first and rounding once is forbidden because it produces a different cent total on half-cent lines. For a `FLEX` lease the same per-line sum runs with the lease's `input_share_pct`, treated as zero when the lease carries none. The `net_settlement_cents` is the `landlord_amount_cents` minus the `input_share_total_cents`. A settlement created with the `ESTIMATED` price source is provisional and informational; only an `ACTUAL` settlement can be finalized.

The settlement lifecycle enforces review in stages. Finalization moves a `PROVISIONAL` settlement to `FINALIZED`, requires the `price_source` to be `ACTUAL` — an attempt on an estimated settlement fails with `ERR_PRICE_NOT_FINAL` — refreshes the `input_share_total_cents` from the currently approved expenses, recomputes the amounts, and records the acting manager in `finalized_by`. Either lease party may dispute a `FINALIZED` settlement: the caller's `X-User-ID` must equal the lease's `tenant_id` or `landlord_id`, else `ERR_NOT_RESOURCE_OWNER`, and a successful dispute moves the settlement to `DISPUTED`. A manager then re-finalizes from `DISPUTED` back to `FINALIZED` by supplying corrected `yield_bu_per_acre` and `harvest_price_cents_per_bu` values; every computed amount is recomputed and `finalized_by` is set anew.

Countersigning is the fiscal close. A manager whose `X-User-ID` differs from `finalized_by` — else `ERR_DUTY_SEGREGATION_VIOLATION` — countersigns a `FINALIZED` settlement, moving it to the terminal `COUNTERSIGNED` state. At that moment the true-up runs. The `billed_amount_cents` is the sum of `amount_cents` over the lease's installments belonging to the term whose `term_index` maps to the settlement's `crop_year`, excluding any adjustment installment created by this settlement itself, while adjustment installments created by earlier settlements do count. The `true_up_cents` is the `net_settlement_cents` minus the `billed_amount_cents`. When the true-up is positive, an adjustment installment is created for the difference: its amount is the true-up, its due date is thirty days after the current clock, it bills the current `term_index`, it starts `SCHEDULED`, it carries an `_adjustment_of` field naming the creating settlement — a field included in the installment's serialized response — and it never feeds back into its own settlement's billed sum. When the true-up is negative, its absolute value is added to the lease's `landlord_credit_cents`, a credit owed back to the tenant. A zero true-up produces neither an adjustment installment nor a landlord credit. Either way the landlord's ledger balances are recomputed. The settlement list accepts optional `lease_id`, `status`, and `crop_year` filters.

### 3.7. Conservation Practices and Tenant Standing

Every conservation practice written into a lease becomes a tracked obligation at activation: one compliance record per entry in `conservation_practices`, starting in `PENDING` status, carrying the lease's `lease_id` and copying the practice's `practice_type` and `due_date`. Each record's `cure_deadline` is its `due_date` plus thirty days — the grace window in which a missed practice can still be evidenced.

The tenant fulfills an obligation by submitting an `evidence_note` describing the work; submission is allowed from `PENDING` and also from `REJECTED`, so evidence rejected once may be replaced before the cure deadline, and the caller must be the lease's tenant, else `ERR_NOT_RESOURCE_OWNER`. Submission moves the record to `EVIDENCE_SUBMITTED`. A manager then verifies the evidence — moving the record to the terminal `VERIFIED` state and recording their `X-User-ID` in `verified_by` — or rejects it with a `reason`, returning the record to `REJECTED`. A manager may also waive the requirement outright with a `reason` from any of `PENDING`, `EVIDENCE_SUBMITTED`, `REJECTED`, or `NON_COMPLIANT`, moving the record to the terminal `WAIVED` state. The compliance-record list accepts optional `lease_id` and `status` filters.

The cure deadline is enforced by the clock. When the clock passes a record's `cure_deadline` with the record still unresolved — still `PENDING`, `EVIDENCE_SUBMITTED`, or `REJECTED` — the sweep moves it to `NON_COMPLIANT` and stamps `noncompliant_at` from the clock. The tenant's `compliance_score` then drops by fifteen points, never falling below a floor of zero. If that drop leaves the score strictly below 50 while the tenant is `APPROVED` — a score of exactly 50 does not suspend — the tenant is moved to `SUSPENDED`, and that suspension cascades exactly as a manual one does: the tenant's bids in `SUBMITTED` or `SHORTLISTED` are withdrawn, and each affected offering recomputes its `eligible_bid_count` and evaluation scores. A `NON_COMPLIANT` record also blocks any future lease activation for that tenant, per §3.4.

Waiving a `NON_COMPLIANT` record is the remedy, but only a partial one: the tenant's `compliance_score` rises by fifteen points, never exceeding the cap of 100, yet the tenant's status does not change back. A suspended tenant regains `APPROVED` standing only through the manual reinstatement of §3.1.

### 3.8. Capital Improvements and Early-Termination Reimbursement

Drainage and other capital works are proposed by managers as improvement projects. The proposal names the `field_id`, optionally links a `lease_id` — the lease whose tenant funds the tenant share, a link required for early-termination reimbursement later — and fixes the `project_type` as `TILE_DRAINAGE`, `IRRIGATION`, `LIMING`, or `FENCING`. The economics are the positive `total_cost_cents`, a `landlord_share_pct` and a `tenant_share_pct` each between 0 and 1 that must sum to exactly 1.0 — any other split is rejected with `ERR_COST_SHARE_INVALID` — a `reimbursement_method` of `STRAIGHT_LINE` or `AGREED_VALUE`, and an `amortization_years` horizon between 1 and 10. The tenant's contribution, `tenant_paid_cents`, is computed at creation as the total cost multiplied by the tenant share, rounded half up to whole cents. A project starts `PROPOSED`, and its `reimbursement_status` starts at `NONE` — a second state dimension that evolves independently of the lifecycle status once the project is completed. The improvement list accepts optional `field_id`, `lease_id`, and `status` filters.

Owner consent is required for capital works, so approval belongs to the landlord: the caller must own the field — the field's `landlord_id` must equal `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` — and when the proposal links a `lease_id`, that lease must be `ACTIVE`, else `ERR_IMPROVEMENT_LEASE_NOT_ACTIVE`. The state guards are strict: approve and reject require the project to be `PROPOSED`; complete and cancel require it to be `APPROVED`; and `mark_reimbursed` requires status `COMPLETED` with `reimbursement_status` `DUE` — any other combination fails with `ERR_INVALID_STATE` (HTTP 409). Approval moves the project to `APPROVED`; rejection, under the same ownership check, moves it to the terminal `REJECTED` state. A manager then marks an approved project completed, moving it to the terminal `COMPLETED` state and stamping `completed_at` from the clock — the amortization epoch — and when the project is a `TILE_DRAINAGE`, completion also sets the field's `drainage_status` to `TILED`. A manager may instead cancel an approved project before completion, moving it to the terminal `CANCELLED` state.

When a lease terminates early, the landlord owes the tenant the unamortized share of every completed improvement linked to that lease whose `reimbursement_status` is still `NONE`; the amount lands in `reimbursement_due_cents`, which is null until then. The elapsed time is the number of days between the project's `completed_at` and the notice's `effective_date`, floored at zero. Under `STRAIGHT_LINE`, the amortization horizon is the `amortization_years` multiplied by 365 — fixed 365-day years, with no leap handling — the remaining days are the horizon minus the elapsed days, floored at zero, and the reimbursement is the `tenant_paid_cents` multiplied by the ratio of remaining days to total days, rounded half up to whole cents. Under `AGREED_VALUE`, a contractual residual schedule applies by elapsed-year bucket — the elapsed days divided by 365 and rounded down: bucket zero returns 100 percent, bucket one 75 percent, bucket two 55 percent, bucket three 35 percent, bucket four 15 percent, and bucket five or beyond 0 percent — and the reimbursement is the `tenant_paid_cents` multiplied by that residual percentage, rounded half up. Once the elapsed time reaches the full horizon, the reimbursement is zero under both methods. Whatever the computed amount — even zero — the project's `reimbursement_status` flips from `NONE` to `DUE`. A manager later marks the payout, moving `reimbursement_status` from `DUE` to `PAID`.

### 3.9. Termination Notices, Auto-Renewal, and Lease Wind-Down

Either lease party may serve a statutory termination notice on an `ACTIVE` lease. The request names the `lease_id` and a `served_by` value that must match the caller's role — a landlord serves as `LANDLORD`, a tenant as `TENANT`, and a mismatch is an `ERR_VALIDATION` failure; a notice against a lease that is not active fails under the generic state rule with `ERR_INVALID_STATE`. At service, `served_date` is stamped from the clock, the `statutory_deadline` is captured as the lease's `term_end_date` minus its `notice_lead_days`, and the `effective_date` is resolved per the deadline semantics of §2.9: service on or before the statutory deadline is on time and the notice takes effect at the current term's `term_end_date`, while late service takes effect at the end of the following term — the renewed `term_end_date` that the missed deadline triggers. The notice starts in `SERVED` status, and the lease moves from `ACTIVE` to `TERMINATION_PENDING`. The notice list accepts optional `lease_id` and `status` filters.

A serving party who changes their mind may withdraw a `SERVED` notice before it becomes effective; the caller must be the serving party and a party to the lease, else `ERR_NOT_RESOURCE_OWNER`. Withdrawal moves the notice to the terminal `WITHDRAWN` state and returns the lease from `TERMINATION_PENDING` to `ACTIVE` — though if the clock has already passed the lease's `current_notice_deadline`, the next renewal sweep will simply renew the lease again.

Renewal is the statutory default when nobody acts. The clock sweep examines every `ACTIVE` lease with no notice in `SERVED` status, and any whose `current_notice_deadline` the clock has strictly passed is renewed for one year: `term_index` increments, `term_end_date` extends by one year, `current_notice_deadline` is recomputed from the new end date, and the lease's `version` increments by one. The one-year extension is a calendar-year extension; when the resulting date would be February 29 of a non-leap year, it falls back to February 28. The base rent escalates at renewal according to the lease's `escalation_type`: under `NONE` it carries forward unchanged, and under `FIXED_PCT` the new base is the previous term's base increased by the `escalation_pct` fraction and rounded half up to whole cents — compounding applies the rounded value of the previous term, not the original base, year after year. New-term installments are then generated per the schedule rules of §3.5.

Effectiveness is the sweep's final word on a notice. When the clock reaches or passes a `SERVED` notice's `effective_date`, the notice becomes `EFFECTIVE` and the lease moves from `TERMINATION_PENDING` to the terminal `TERMINATED` state. Termination cascades: the field returns from `LEASED` to `AVAILABLE`; every completed improvement linked to the lease whose `reimbursement_status` is `NONE` computes its `reimbursement_due_cents` per §3.8 and flips to `DUE`; when the landlord is an absentee owner, a `TERMINATION`-type owner report is auto-created in `DRAFT` status covering the closed window from the final term's `term_start_date` through the `effective_date`; and the landlord's ledger balances are recomputed.

### 3.10. Owner Reporting and Absentee-Landlord Escalation

Reporting keeps owners — especially absentee ones — informed. A manager generates a report by naming the `landlord_id`, a `report_type` of `QUARTERLY`, `ANNUAL`, `SETTLEMENT`, or `TERMINATION`, and the closed window `[period_start, period_end]` with both ends inclusive. A `period_start` later than the `period_end` is rejected with `ERR_INVALID_PERIOD`, and a window that overlaps any existing report for the same landlord — touching endpoints already count as overlap under the closed-interval semantics of §2.9 — is rejected with `ERR_REPORT_PERIOD_OVERLAP`.

The aggregates are computed once, at creation. The `rent_collected_cents` is the sum of `paid_cents` over the installments of this landlord's leases whose `last_payment_at` falls inside the window: an installment contributes its full current `paid_cents` to whichever window contains its most recent payment, and an installment never paid contributes zero. The `expenses_approved_cents` is the sum of `landlord_share_cents` over this landlord's leases' `APPROVED` expense records whose `approved_at` falls inside the window. The `noncompliant_count` is the count of this landlord's leases' compliance records whose `noncompliant_at` falls inside the window. A window with no matching rows yields zeros — never nulls, never an error. A new report starts in `DRAFT` status with `sent_at`, `ack_due_date`, and `acknowledged_at` all null and `escalation_required` false.

Sending moves a report from `DRAFT` to `SENT`, stamps `sent_at` from the clock, and sets the `ack_due_date` to `sent_at` plus the landlord's `ack_required_days`; delivery honors the landlord's `report_channel`. Acknowledgment belongs to the recipient: the caller's `X-User-ID` must equal the report's `landlord_id`, else `ERR_NOT_RESOURCE_OWNER`, and a successful acknowledgment moves the report to the terminal `ACKNOWLEDGED` state, stamps `acknowledged_at`, and clears `escalation_required`. The escalation flag is a computed signal rather than a status: the clock sweep sets `escalation_required` true whenever the landlord is `absentee`, the report is `SENT`, and the clock has passed the `ack_due_date`. The report list accepts optional `landlord_id` and `status` filters.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201; endpoints that modify, transition, or act on an existing resource respond with 200, as do all reads. Request and response payloads for each endpoint are reconstructed from the workflow narratives of §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock and run all due sweeps | FarmManager |
| POST | /landlords | Create a landlord (farm owner, possibly absentee) | FarmManager |
| GET | /landlords/{landlordId} | Get a landlord | FarmManager, Landlord, Tenant |
| GET | /landlords | List landlords | FarmManager, Landlord, Tenant |
| POST | /tenants | Create a tenant operator | FarmManager |
| GET | /tenants/{tenantId} | Get a tenant | FarmManager, Landlord, Tenant |
| GET | /tenants | List tenants | FarmManager, Landlord, Tenant |
| POST | /tenants/{tenantId}/approve | Approve an applicant or reinstate a suspended tenant | FarmManager |
| POST | /tenants/{tenantId}/suspend | Suspend an approved tenant; cascades to bids | FarmManager |
| POST | /fields | Create a field for a landlord | FarmManager |
| GET | /fields/{fieldId} | Get a field | FarmManager, Landlord, Tenant |
| GET | /fields | List fields | FarmManager, Landlord, Tenant |
| POST | /offerings | Open a lease offering (bid solicitation) for a field | FarmManager |
| GET | /offerings/{offeringId} | Get an offering | FarmManager, Landlord, Tenant |
| GET | /offerings | List offerings | FarmManager, Landlord, Tenant |
| POST | /offerings/{offeringId}/close | Close an offering to further bidding | FarmManager |
| POST | /offerings/{offeringId}/award | Landlord selects the winning bid | Landlord |
| POST | /offerings/{offeringId}/cancel | Cancel an offering | FarmManager |
| POST | /bids | Tenant submits a bid on an offering | Tenant |
| GET | /bids/{bidId} | Get a bid | FarmManager, Landlord, Tenant |
| GET | /bids | List bids | FarmManager, Landlord, Tenant |
| PATCH | /bids/{bidId} | Revise a SUBMITTED bid's amounts | Tenant |
| POST | /bids/{bidId}/withdraw | Tenant withdraws own bid | Tenant |
| POST | /bids/{bidId}/shortlist | Manager shortlists a submitted bid | FarmManager |
| POST | /bids/{bidId}/demote | Manager demotes a shortlisted bid | FarmManager |
| POST | /leases | Create a DRAFT lease from an awarded bid | FarmManager |
| GET | /leases/{leaseId} | Get a lease | FarmManager, Landlord, Tenant |
| GET | /leases | List leases | FarmManager, Landlord, Tenant |
| PATCH | /leases/{leaseId} | Amend a lease | FarmManager |
| POST | /leases/{leaseId}/activate | Activate a DRAFT lease | FarmManager |
| POST | /leases/{leaseId}/cancel | Cancel a DRAFT lease | FarmManager |
| GET | /installments/{installmentId} | Get an installment | FarmManager, Landlord, Tenant |
| GET | /installments | List installments | FarmManager, Landlord, Tenant |
| POST | /installments/{installmentId}/record_payment | Record a payment against an OPEN or LATE installment | FarmManager |
| POST | /installments/{installmentId}/reverse_payment | Reverse all payments on a PAID installment | FarmManager |
| POST | /installments/{installmentId}/waive | Waive an outstanding installment balance | FarmManager |
| POST | /settlements | Create a PROVISIONAL harvest settlement | FarmManager |
| GET | /settlements/{settlementId} | Get a settlement | FarmManager, Landlord, Tenant |
| GET | /settlements | List settlements | FarmManager, Landlord, Tenant |
| POST | /settlements/{settlementId}/finalize | Finalize a PROVISIONAL settlement | FarmManager |
| POST | /settlements/{settlementId}/countersign | Countersign a FINALIZED settlement and post the true-up | FarmManager |
| POST | /settlements/{settlementId}/dispute | Lease party disputes a FINALIZED settlement | Tenant, Landlord |
| POST | /settlements/{settlementId}/refinalize | Correct and re-finalize a DISPUTED settlement | FarmManager |
| POST | /expenses | Tenant submits an input cost for sharing | Tenant |
| GET | /expenses/{expenseId} | Get an expense record | FarmManager, Landlord, Tenant |
| GET | /expenses | List expense records | FarmManager, Landlord, Tenant |
| POST | /expenses/{expenseId}/approve | Approve a submitted expense | FarmManager |
| POST | /expenses/{expenseId}/reject | Reject a submitted expense | FarmManager |
| GET | /compliance-records/{recordId} | Get a compliance record | FarmManager, Landlord, Tenant |
| GET | /compliance-records | List compliance records | FarmManager, Landlord, Tenant |
| POST | /compliance-records/{recordId}/submit_evidence | Lease tenant submits practice evidence | Tenant |
| POST | /compliance-records/{recordId}/verify | Verify submitted evidence | FarmManager |
| POST | /compliance-records/{recordId}/reject_evidence | Reject submitted evidence | FarmManager |
| POST | /compliance-records/{recordId}/waive | Waive a practice requirement | FarmManager |
| POST | /improvements | Propose an improvement/drainage project | FarmManager |
| GET | /improvements/{improvementId} | Get an improvement project | FarmManager, Landlord, Tenant |
| GET | /improvements | List improvement projects | FarmManager, Landlord, Tenant |
| POST | /improvements/{improvementId}/approve | Landlord approves a proposed project | Landlord |
| POST | /improvements/{improvementId}/reject | Landlord rejects a proposed project | Landlord |
| POST | /improvements/{improvementId}/complete | Mark an approved project completed | FarmManager |
| POST | /improvements/{improvementId}/cancel | Cancel an approved project | FarmManager |
| POST | /improvements/{improvementId}/mark_reimbursed | Mark a due reimbursement as paid out | FarmManager |
| POST | /notices | Serve a statutory termination notice on an ACTIVE lease | Landlord, Tenant |
| GET | /notices/{noticeId} | Get a termination notice | FarmManager, Landlord, Tenant |
| GET | /notices | List termination notices | FarmManager, Landlord, Tenant |
| POST | /notices/{noticeId}/withdraw | Serving party withdraws a SERVED notice | Landlord, Tenant |
| POST | /reports | Generate a landlord report over a closed period window | FarmManager |
| GET | /reports/{reportId} | Get an owner report | FarmManager, Landlord, Tenant |
| GET | /reports | List owner reports | FarmManager, Landlord, Tenant |
| POST | /reports/{reportId}/send | Send a draft report to the landlord | FarmManager |
| POST | /reports/{reportId}/acknowledge | Landlord acknowledges a sent report | Landlord |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the guarded workflow lives; this table is an index of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_DUTY_SEGREGATION_VIOLATION | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_TENANT_NOT_APPROVED | 409 |
| ERR_TENANT_NONCOMPLIANT | 409 |
| ERR_BID_WINDOW_CLOSED | 409 |
| ERR_BID_ACCEPTANCE_EXPIRED | 409 |
| ERR_BID_ALREADY_LEASED | 409 |
| ERR_BID_BELOW_MINIMUM | 409 |
| ERR_FIELD_LEASE_OVERLAP | 409 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_INVALID_PERIOD | 422 |
| ERR_SETTLEMENT_NOT_APPLICABLE | 409 |
| ERR_SETTLEMENT_YEAR_FINAL_EXISTS | 409 |
| ERR_PRICE_NOT_FINAL | 409 |
| ERR_INPUT_SHARING_NOT_APPLICABLE | 409 |
| ERR_COST_SHARE_INVALID | 422 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |
| ERR_WAIVER_EXCEEDS_AUTHORITY | 409 |
| ERR_IMPROVEMENT_LEASE_NOT_ACTIVE | 409 |
| ERR_STALE_VERSION | 412 |
