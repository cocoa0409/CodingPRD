# Airport Rental Car CFC API — Product Requirements Document

## 1. Introduction

A consolidated rental car facility — a ConRAC — is one of the few pieces of airport infrastructure whose entire capital stack, operating budget and tenant billing run off a single per-customer levy. Travellers pay a Customer Facility Charge on every on-airport transaction day; the airport authority collects that charge through the rental car brands, pledges it to bond debt service, funds the shuttle bus fleet and the capital improvement programme out of what remains, and simultaneously bills each brand a concession rent that is the greater of a negotiated minimum annual guarantee and a percentage of its gross revenue. Today most airports run this on spreadsheets that reconcile once a quarter, which is precisely when a covenant deficiency, an overbooked ready-return row, or a percentage-rent underbilling is discovered — months after it could have been prevented.

This document specifies the Airport Rental Car Facility and Customer Facility Charge Administration service, a back-office REST API that makes the ConRAC's money and space ledgers continuously correct rather than periodically reconciled. Four constituencies share the system. Airport property managers build and govern the physical and contractual inventory. Rental car operators report their activity, request counter and fleet parking space, and remit the charges they have collected. Audit officers confirm reported figures and issue the year-end true-up. Treasury officers steward the CFC trust, service the bonds and release capital draws. Because these constituencies have opposing incentives, the service enforces segregation of duties in software: the officer who requests a capital draw cannot authorise it, and the officer who accepted a year's transaction-day reports cannot issue the settlement computed from them.

Every collection in the service is mounted flat beneath `/rac`. There are no nested routes: a child record is reached by filtering its own collection, never by walking through its parent's URL. The specification that follows is organised as global contracts (§2), the business narratives that describe how the ConRAC actually operates (§3), a compact endpoint index (§4) and the error catalogue (§5). The endpoint index deliberately carries no request or response schemas — the payloads are described in the narratives, because understanding *when* a field is supplied matters more than knowing that it exists.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operating Parties and Role-Based Access Control

Every request to the service must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. Exactly four roles are recognised, and their spellings are fixed: `FacilityAdmin`, `ConcessionaireOperator`, `AuditOfficer`, and `FinanceOfficer`. If either header is absent, or if `X-User-Role` carries any string other than those four, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined. A caller whose role is recognised but who is not among the roles authorised for the endpoint being called receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

A `FacilityAdmin` is the airport authority's property manager. This role builds the facility inventory, registers rental car brands, drafts and runs concession agreements, governs the capital improvement programme, and drives the service's logical clock. When `X-User-Role` is `FacilityAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it where a workflow captures the acting user, but it is never compared against any row's `id`.

An `AuditOfficer` is the transaction-day audit authority: it opens audits, accepts or rejects reported figures, and issues the minimum-guarantee true-up. When `X-User-Role` is `AuditOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it as `audited_by_user_id` on a report the officer accepts and as `issued_by_user_id` on a settlement the officer issues, but it never compares it to any entity's `id`.

A `FinanceOfficer` is the CFC trust and bond treasury. This role receives remittances, funds and pays debt service, allocates shuttle operating cost, and authorises, rejects, pays or voids capital draws. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `requested_by_user_id` and `authorized_by_user_id` on capital draws, but performs no lookup of it as an entity `id`.

The fourth role is different in kind. When `X-User-Role` is `ConcessionaireOperator`, `X-User-ID` is the `id` of the acting `Concessionaire` row — the value returned when the airport authority registered that rental car brand. Ownership checks on any resource that references a `Concessionaire` compare the resource's owning brand to `X-User-ID`: for every write endpoint whose authorised roles include `ConcessionaireOperator`, the server resolves the target resource's `agreement_id` to a `ConcessionAgreement`, reads that agreement's `concessionaire_id`, and requires it to equal `X-User-ID`. When it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Read endpoints impose no such ownership filter — all four roles may read every resource in the service.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` defaults to 0 and may not be negative. A `limit` outside the 1-to-100 range, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Beyond `limit` and `offset`, each collection accepts its own filters, and an unrecognised value for an enumerated filter is an `ERR_INVALID_REQUEST`. Concessionaires, fleet parking zones, debt-service obligations, shuttle cost periods and capital projects filter on `facility_id`; obligations, periods and projects additionally filter on `status`, and projects also on `predecessor_project_id`. Concession agreements filter on `facility_id`, `concessionaire_id`, `contract_status` and `compliance_status`. Counter spaces filter on `facility_id` and `space_class`. Counter assignments filter on `agreement_id`, `counter_space_id` and `status`. Fleet allocations filter on `agreement_id`, `zone_id` and `status`. Transaction-day reports filter on `agreement_id`, `status`, `period_year` and `period_month`. CFC remittances filter on `agreement_id`, `report_id` and `status`. Shuttle cost allocation lines filter on `shuttle_period_id` and `agreement_id`. Capital disbursements filter on `project_id` and `status`. True-up settlements filter on `agreement_id` and `status`. Every filter is optional, and filters combine conjunctively.

Results are always ordered by `created_at` ascending unless a business narrative in §3 states a different ordering for a cascade. The `meta` object of a list response carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before the page window is applied, and `has_more` as a boolean that is true when rows remain beyond the current window.

### 2.4. Resource Identity, Timestamps, and the Version Counter

Every resource carries a server-minted `id` that is a UUID string with no type prefix; clients never supply an `id`. Every resource also carries a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, recorded when the row was inserted.

Most resources additionally carry `updated_at`, refreshed to the current instant on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row. When a workflow in §3 says that an operation "advances" or "increments" some entity's `version`, it means exactly this: that row's `version` rises by 1 and its `updated_at` is refreshed, whether the row was the direct target of the request or was touched as a downstream consequence of it.

`ShuttleCostAllocation` is the single exception. Its rows are immutable ledger lines created only as a by-product of allocating a shuttle cost pool, and they carry only `id` and `created_at`: both `updated_at` and `version` are absent from a shuttle cost allocation line. Every other resource in the service — `Facility`, `Concessionaire`, `ConcessionAgreement`, `CounterSpace`, `CounterAssignment`, `FleetParkingZone`, `FleetAllocation`, `TransactionDayReport`, `CfcRemittance`, `DebtServiceObligation`, `ShuttleCostPeriod`, `CapitalProject`, `CapitalDisbursement` and `TrueUpSettlement` — carries the full set of `id`, `created_at`, `updated_at` and `version`.

### 2.5. Path Resolution and Foreign-Key Admission

Paths in this service are flat: a resource identifier in the URL names exactly one row, and there is never more than one path parameter in a single path. Path parameters are nevertheless validated left to right, and a path parameter that names no existing row rejects the request before any body field is examined, with the not-found code belonging to that resource type: `facility_id` yields `ERR_FACILITY_NOT_FOUND`, `concessionaire_id` yields `ERR_CONCESSIONAIRE_NOT_FOUND`, `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`, `counter_space_id` yields `ERR_COUNTER_SPACE_NOT_FOUND`, `counter_assignment_id` yields `ERR_COUNTER_ASSIGNMENT_NOT_FOUND`, `zone_id` yields `ERR_ZONE_NOT_FOUND`, `fleet_allocation_id` yields `ERR_FLEET_ALLOCATION_NOT_FOUND`, `report_id` yields `ERR_REPORT_NOT_FOUND`, `remittance_id` yields `ERR_REMITTANCE_NOT_FOUND`, `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`, `shuttle_period_id` yields `ERR_SHUTTLE_PERIOD_NOT_FOUND`, `shuttle_allocation_id` yields `ERR_SHUTTLE_ALLOCATION_NOT_FOUND`, `project_id` yields `ERR_PROJECT_NOT_FOUND`, `disbursement_id` yields `ERR_DISBURSEMENT_NOT_FOUND`, and `settlement_id` yields `ERR_SETTLEMENT_NOT_FOUND`. All of these carry HTTP 404.

Foreign keys supplied in a request body are resolved the same way and with the same error codes, in the order in which the endpoint's input fields are listed in §3's description of that operation. A creation payload naming both a facility and a concessionaire therefore surfaces `ERR_FACILITY_NOT_FOUND` when both are bogus, because the facility reference is listed first. `predecessor_project_id`, when supplied, is a reference to another capital project and yields `ERR_PROJECT_NOT_FOUND` when it resolves to nothing.

### 2.6. Request Admission Order

The service evaluates a request through a fixed ladder of checks, and the first check that fails determines the response. Implementations must respect this ordering, because a request that violates several rules at once has exactly one correct error code.

1. Authentication: the headers are present and `X-User-Role` is one of the four declared roles, else `ERR_UNAUTHENTICATED` (401).
2. Role authorisation: the acting role is authorised for the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403).
3. Request shape: every required input field is present, every value has the declared type, every enum-typed value is a legal member of its enumeration, every integer satisfies its declared range, every date parses as `YYYY-MM-DD`, and pagination stays within its bounds; otherwise `ERR_INVALID_REQUEST` (400).
4. Path existence: every resource named in the path exists, validated left to right, else the matching not-found code (404).
5. Body foreign keys: every foreign key in the body resolves, validated in the order the endpoint lists its input fields, else the matching not-found code (404).
6. Ownership: when the acting role is `ConcessionaireOperator`, `X-User-ID` must equal the `Concessionaire` reached from the target resource through its agreement, else `ERR_NOT_RESOURCE_OWNER` (403).
7. State: the target resource sits in a from-state that the requested transition declares, else `ERR_INVALID_STATE` (409).
8. Optimistic concurrency: the supplied parent version matches the parent's current `version`, else `ERR_STALE_VERSION` (412).
9. Segregation of duties on capital draws (403), then 10. segregation of duties on true-up issuance (403).
11. Counter activation requires an active agreement (409), then 12. capital draw authorisation requires a funded project (409), then 13. project close or cancel requires zero encumbrance (409), then 14. capital draw authorisation requires a satisfied bond covenant (409), then 15. a capital draw request requires its project's predecessor gate to be clear (409).
16. Date-range sanity on space requests (422), then 17. containment of the requested interval inside the agreement term (422).
18. Counter space exclusive occupancy (409), then 19. fleet zone aggregate capacity (409), then 20. overflow lot exhaustion (409), then 21. duplicate reporting period (409), then 22. duplicate brand code (409), then 23. duplicate space label (409), then 24. duplicate remittance (409), then 25. duplicate settlement (409).
26. Report-to-agreement referential agreement (422), then 27. remittance basis against report status (422), then 28. contract-year agreement (422), then 29. all reports finalised before a true-up may be issued (409), then 30. a non-empty shuttle allocation basis (422).
31. Debt-service coverage (409), then 32. project budget (409), then 33. capital fund sufficiency (409), then 34. settlement payment sufficiency (422).

The precise condition guarding each of these numbered checks, and the exact error code it raises, is described in the business narrative that owns it. What matters globally is the ordering: a stale parent version, for instance, is reported only after the target's state has been found acceptable, and a bond covenant deficiency is reported only after the project has been confirmed to be funded.

### 2.7. Money, Basis Points, and Rounding

All monetary amounts in this service are integer cents. No field carries a fractional currency value, and no response ever contains a floating-point money figure. Rates are expressed in basis points, where 10,000 basis points is one hundred percent; a percentage rent of two and a half percent is therefore `percentage_rent_rate_bps` of 250.

Two rounding disciplines are used, and the narrative always says which. Where a basis-point rate is applied to an amount, the product is divided by 10,000 and rounded half up to a whole cent. Where a pool is divided among claimants, or where a monthly figure is derived from an annual one, the division is truncated downward to a whole cent and the discarded fractions are accounted for explicitly — either by a residue bucket or by a largest-remainder distribution, as the relevant narrative describes. The only non-integer value the service exposes is `coverage_ratio_at_funding`, a display figure rounded half up to four decimal places.

### 2.8. The CFC Trust Ledger

Each facility owns a Customer Facility Charge trust whose cash position is exposed as seven running balances plus a lifetime counter, all in integer cents. `trust_debt_service_reserve_cents` holds unencumbered debt-service reserve. `trust_debt_service_funded_cents` holds cash committed to obligations that have been funded but not yet paid. `trust_om_reserve_cents` holds the operations and maintenance reserve. `trust_capital_fund_cents` holds unencumbered capital-project cash. `trust_unallocated_cents` holds residue that exceeded every bucket's target. `trust_encumbered_cents` holds capital cash reserved against authorised but unpaid draws. `trust_disbursed_cents` holds cash that has permanently left the trust, whether through a paid obligation or a paid draw. Separately, `trust_lifetime_received_cents` accumulates every cent the trust has ever received and never decreases.

The covenant posture of the facility is published as `bond_coverage_status`, an enumeration of exactly `SATISFIED` and `DEFICIENT`. It is recomputed whenever any trust bucket moves: it reads `SATISFIED` when the sum of `trust_debt_service_reserve_cents` and `trust_debt_service_funded_cents` is greater than or equal to `ds_reserve_requirement_cents`, and `DEFICIENT` otherwise. Note the consequence at registration time: a facility whose `ds_reserve_requirement_cents` is greater than zero begins life `DEFICIENT`, while a facility that requires no debt-service reserve at all begins `SATISFIED`.

The trust obeys a conservation identity that no operation may break. Every cent that enters through a remittance receipt lands in exactly one of the debt-service reserve, O&M reserve, capital fund or unallocated buckets; every cent that moves between buckets leaves one and enters another in the same request; and only a paid obligation or a paid draw removes cents from the trust's live buckets into `trust_disbursed_cents`.

### 2.9. Optimistic Concurrency on Parent Records

Three creation operations attach a child row to a parent whose own state the client must have observed first. Because two such children can legitimately coexist, no state precondition rejects the later write — so these three writes instead carry the parent's `version` as a mandatory, non-optional input field, and the server rejects the write when the value is stale.

A request creating a counter assignment must carry `expected_agreement_version`, holding the `version` of the `ConcessionAgreement` named by `agreement_id` as the client last observed it. If any writer has advanced that agreement's `version` since — an execution, a suspension, another counter assignment, an accepted report — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot bind space to an agreement whose term dates, counter tally or compliance posture it has not seen.

A request creating a fleet allocation must carry `expected_zone_version`, holding the `version` of the `FleetParkingZone` named by `zone_id` as the client last observed it. A mismatch against the zone's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from sizing a stall request against a zone occupancy reading that has since moved.

A request creating a capital disbursement must carry `expected_project_version`, holding the `version` of the `CapitalProject` named by `project_id` as the client last observed it. A mismatch against the project's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so a draw is never requested against a budget, encumbrance or funding state the client has not observed.

No other endpoint in the service accepts a version field. Action endpoints that drive state transitions are protected by their from-state preconditions instead, and supplying a version to them is not part of their contract.

### 2.10. Segregation of Duties

Two decisions in this service must be made by a different human being than the one who set them up, and the service enforces this on `X-User-ID` alone.

On capital draws, the `X-User-ID` captured as `requested_by_user_id` when the draw was created may neither authorise nor reject that same draw. Both of those actions therefore compare the acting `X-User-ID` against `requested_by_user_id` and reject a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

On true-up issuance, an `AuditOfficer` whose `X-User-ID` appears as `audited_by_user_id` on any `ACCEPTED` transaction-day report of the agreement may not issue a true-up settlement for that agreement. A match on any such report rejects the issuance with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This applies to both the initial issuance and any re-issuance after a dispute.

### 2.11. The Logical Clock and Calendar Conventions

The service does not read wall-clock time for business decisions. It keeps a logical clock, exposed on every facility as `current_utc`, which reads exactly `2026-08-01T00:00:00Z` until an administrator moves it and never falls back to real time. Moving the clock is a test-driving capability restricted to `FacilityAdmin`; the caller supplies the instant to move to as `to_iso8601`, and the response reports the new `current_utc` together with `delinquent_remittance_count`, `deferred_obligation_count` and `expired_agreement_count` describing what the move swept.

Calendar dates in this service are `YYYY-MM-DD` strings, and interval conventions differ deliberately between the two space-booking domains. Counter and ready-return occupancy uses a half-open interval: `effective_start_date` is included and `effective_end_date` is excluded, so one assignment ending on the day another begins is not a collision. Fleet parking allocation uses a closed interval: both `start_date` and `end_date` are occupied days, so two allocations that merely touch on a single calendar day do collide, and the number of days an allocation spans is the difference between its two dates in days plus one.

## 3. Business Logic & Workflows

### 3.1. Standing Up the ConRAC Inventory

Everything in the service hangs off a facility. A `FacilityAdmin` registers one by supplying `code`, a three-to-eight character uppercase identifier that must be unique across facilities, and `name`, the display name of the consolidated rental car facility. The same payload fixes the economics: `cfc_rate_per_transaction_day_cents` is the Customer Facility Charge levied per on-airport transaction day and may not be negative; `ds_reserve_requirement_cents` is the bond debt-service reserve that CFC receipts must fund; `om_reserve_requirement_cents` is the operations and maintenance reserve; and `capital_fund_cap_cents` is the ceiling on the capital fund bucket, above which incoming cash spills to residue. None of these four may be negative. The physical overflow inventory arrives in the same payload as `overflow_lot_stalls`, the total number of stalls in the shared remote overflow lot, which also may not be negative.

Two facility fields are optional at registration. `overflow_daily_surcharge_cents`, the per-stall per-day surcharge billed for overflow-lot stalls, defaults to 0 when omitted. `remittance_grace_days`, the number of days after a reporting period's last calendar day before an unpaid Customer Facility Charge remittance falls delinquent, defaults to 20 when omitted — the float an operator is given to move the cash it has already collected from travellers.

On registration all seven trust buckets and `trust_lifetime_received_cents` start at 0, `funded_obligation_count` starts at 0, `overflow_stalls_allocated` starts at 0 and `overflow_stalls_available` therefore equals `overflow_lot_stalls`, `bond_coverage_status` is computed as described in §2.8, and `current_utc` reports the logical clock. Thereafter `overflow_stalls_available` is always the facility's `overflow_lot_stalls` minus its `overflow_stalls_allocated`, and `overflow_stalls_allocated` is always the total of `overflow_stalls_granted` across the facility's fleet allocations that are still in `ALLOCATED` status.

Rental car brands are registered next. A brand row carries `facility_id`, its registered `legal_name`, a `brand_code` of two to eight uppercase characters, and a `contact_email` for billing correspondence. Two brands at the same facility may not share a `brand_code`; an attempt to reuse one is rejected with `ERR_DUPLICATE_BRAND_CODE`. The `id` minted for a brand is operationally significant: it is the value a `ConcessionaireOperator` presents as `X-User-ID`. A newly registered brand starts with `agreement_count` of 0, which rises by 1 each time an agreement naming it is drafted.

Counter and ready-return space is inventory, not booking. Each space carries `facility_id`, a `terminal_code` naming the terminal or level it sits on, a `space_label` that must be unique within the facility, and a `space_class` of either `COUNTER` for rental counters or `READY_RETURN` for ready and return stalls. A repeated `space_label` at the same facility is rejected with `ERR_DUPLICATE_SPACE_LABEL`. A new space begins unoccupied, with `active_assignment_id` null and `assignment_count` of 0; the latter counts the assignments on that space whose status is either `ALLOCATED` or `ACTIVE`.

Fleet parking is inventoried as zones. A zone carries `facility_id`, a `zone_label` as painted on the parking deck, and a `stall_capacity` that may not be negative. A zone begins with `stalls_allocated` of 0 and `stalls_available` equal to `stall_capacity`; from then on `stalls_allocated` is the total of `zone_stalls_granted` over the zone's allocations still in `ALLOCATED` status, and `stalls_available` is always `stall_capacity` minus `stalls_allocated`.

### 3.2. The Concession Agreement and Its Two Independent Status Axes

A concession agreement is drafted by a `FacilityAdmin` and binds one brand to one contract year at one facility. Its payload names the `facility_id` and the `concessionaire_id`, states the one-based `contract_year_index` (which must be at least 1), and delimits the year with `term_start_date` and `term_end_date`, both `YYYY-MM-DD` and both inclusive. The commercial terms are `mag_annual_cents`, the Minimum Annual Guarantee for the year, which may not be negative; `percentage_rent_rate_bps`, the percentage rent rate in basis points, which must fall between 0 and 10000 inclusive; and `rent_settlement_basis`, an enumeration of exactly `CUMULATIVE_YTD` and `MONTHLY_STANDALONE` that selects which of two very different rent variants governs the agreement for its whole life. Drafting an agreement raises the named brand's `agreement_count` by 1.

A freshly drafted agreement begins with `contract_status` of `DRAFT` and `compliance_status` of `COMPLIANT`, and with every ledger field at zero: `gross_revenue_ytd_cents`, `transaction_days_ytd`, `accepted_report_count`, `percentage_rent_accrued_cents`, `rent_billed_to_date_cents`, `last_installment_cents`, `mag_shortfall_cents`, `counter_units_assigned` and `fleet_stalls_allocated` all start at 0, and `rent_tier` starts at `MAG_FLOOR`.

The crucial structural point about an agreement is that it carries **two status axes on one row, and they advance on entirely separate clocks**. `contract_status` is the contractual lifecycle axis, taking the values `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATED` and `EXPIRED`, of which `TERMINATED` and `EXPIRED` are terminal. It is moved only by the property manager's lifecycle actions and by the logical clock. `compliance_status` is the independent compliance axis, taking the values `COMPLIANT`, `DELINQUENT` and `COVENANT_BREACH`, none of which is terminal. It is moved only by remittance and audit events. Neither axis ever reads or writes the other: an `ACTIVE` agreement stays `ACTIVE` while it is `DELINQUENT`, and executing or suspending an agreement leaves `compliance_status` untouched.

Executing a drafted agreement carries `contract_status` from `DRAFT` to `ACTIVE`. It requires the agreement to be in `DRAFT` and requires `term_start_date` to be strictly earlier than `term_end_date`; the brand's `agreement_count` is not touched, because it was already raised when the agreement was drafted. Suspending an agreement carries it from `ACTIVE` to `SUSPENDED`, and it does not merely change a label: every counter assignment of that agreement currently in `ACTIVE` status falls back to `ALLOCATED`, and the `active_assignment_id` of each corresponding counter space is cleared to null, so the physical positions are surrendered while the suspension lasts. Reinstating a suspended agreement carries it from `SUSPENDED` back to `ACTIVE`, closing the `ACTIVE → SUSPENDED → ACTIVE` loop, which an agreement may cycle through any number of times. Each of these three lifecycle actions advances the agreement's `version` by 1, and all three are reserved to `FacilityAdmin`.

Time closes an agreement out. When the logical clock is advanced past an agreement's `term_end_date` — that is, when the clock's calendar date is strictly later than `term_end_date` — an agreement in `ACTIVE` moves to `EXPIRED`, and an agreement in `SUSPENDED` moves to `TERMINATED`. The two endings are not cosmetically different. Expiry from `ACTIVE` only advances the agreement's `version`; termination from `SUSPENDED` additionally releases the tenant's whole counter footprint, setting every counter assignment of the agreement whose status is `ALLOCATED` or `ACTIVE` to `RELEASED` and decrementing each affected counter space's `assignment_count` accordingly, before advancing the agreement's `version`. Agreements swept into either terminal state are counted in the clock response's `expired_agreement_count`.

On the compliance axis, an agreement moves from `COMPLIANT` to `DELINQUENT` when the logical clock pushes one of its Customer Facility Charge remittances past its `due_date` while that remittance is still `PENDING`; the remittance itself moves to `DELINQUENT` in the same sweep and the agreement's `version` advances. It returns from `DELINQUENT` to `COMPLIANT` when a treasury receipt brings the last outstanding remittance to `RECONCILED` and no remittance of that agreement remains `DELINQUENT` afterwards. It moves from either `COMPLIANT` or `DELINQUENT` to `COVENANT_BREACH` when an audit acceptance records a positive variance assessment against it — both of those inbound branches are real, and both advance the agreement's `version`. It returns from `COVENANT_BREACH` to `COMPLIANT` only when a true-up settlement for that agreement, sitting in `ISSUED`, is settled with a payment that covers its net amount.

### 3.3. Occupying Counter and Ready-Return Space

Space is claimed in two steps: an operator first reserves a window on a space, then activates the reservation when it physically takes the position. A reservation names the `agreement_id` holding the space and the `counter_space_id` being occupied, and delimits the occupancy with `effective_start_date` and `effective_end_date`. The interval is half-open — the start date is occupied and the end date is not — and the request must also carry `expected_agreement_version` as described in §2.9.

Four business rules guard the reservation, and their relative order matters when a payload violates more than one. Date sanity comes first: `effective_start_date` must be strictly earlier than `effective_end_date`, and a payload that reverses or collapses the window is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422). Term containment comes next: the requested window must lie inside the agreement's closed term running from `term_start_date` through `term_end_date` inclusive, and a window that pokes outside it in either direction is rejected with `ERR_OUTSIDE_AGREEMENT_TERM` (HTTP 422). Exclusive occupancy comes last of the three: the reservation is rejected with `ERR_COUNTER_SPACE_OCCUPIED` (HTTP 409) when some existing assignment on the same `counter_space_id`, whose status is `ALLOCATED` or `ACTIVE`, satisfies both halves of the half-open overlap test — the new start date is strictly earlier than the existing end date, and the existing start date is strictly earlier than the new end date. Because both comparisons are strict, a new window whose start date equals an existing window's end date does not collide, and back-to-back tenancies on a single counter are legal. The fourth guard is the stale-version check of §2.9, which is evaluated before all three of these.

A successful reservation is created in `ALLOCATED` status. It raises the counter space's `assignment_count` by 1 and the agreement's `counter_units_assigned` by 1, and advances both the agreement's `version` and the counter space's `version` by 1 each.

Activation moves an assignment `ALLOCATED → ACTIVE`. It requires the assignment to be in `ALLOCATED`, requires the counter space's `active_assignment_id` to be null so that no other tenant physically holds the position, and requires the referenced agreement's `contract_status` to be exactly `ACTIVE` — an agreement sitting in `DRAFT`, `SUSPENDED`, `EXPIRED` or `TERMINATED` cannot have space activated against it, and the attempt is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). On success the space's `active_assignment_id` is set to the activating assignment's `id`, and both the assignment's `version` and the space's `version` advance by 1.

Release is available from either `ALLOCATED` or `ACTIVE`, and both branches land in the terminal `RELEASED` status. Releasing from `ALLOCATED` lowers the counter space's `assignment_count` by 1 and the agreement's `counter_units_assigned` by 1, and stamps `released_on_date` with the logical clock's calendar date. Releasing from `ACTIVE` does all of that and additionally clears the space's `active_assignment_id` back to null, because the position it pointed at has just been vacated. `released_on_date` is null on any assignment that has not been released. Both release branches advance the assignment's `version` by 1 and the counter space's `version` by 1.

### 3.4. Fleet Parking Allocation and the Overflow Lot

A fleet allocation is a request for stalls over a closed interval, and unlike counter occupancy it is an *aggregate* capacity claim rather than an exclusive one: many operators share a zone, and the zone's `stall_capacity` is the ceiling on their combined presence at any moment. The payload names the `agreement_id` holding the stalls and the `zone_id` of the primary zone to draw from, delimits the interval with `start_date` and `end_date` — both inclusive — states `stalls_requested`, which must be at least 1, and may carry `allow_overflow`, a boolean that defaults to false when omitted. It must also carry `expected_zone_version` as described in §2.9.

Interval sanity for a fleet allocation is more permissive than for a counter assignment: `start_date` must be no later than `end_date`, so a single-day allocation is legal, and a payload whose start falls after its end is rejected with `ERR_INVALID_DATE_RANGE`. The interval must then lie inside the agreement's closed term running from `term_start_date` through `term_end_date`, or the request is rejected with `ERR_OUTSIDE_AGREEMENT_TERM`.

Granting proceeds as a two-stage waterfall over the requested stalls. First the zone is drawn down. Every allocation on the same `zone_id` that is still in `ALLOCATED` status and whose interval overlaps the requested one is gathered, where overlap on these closed intervals holds when the new start date is no later than the existing end date and the existing start date is no later than the new end date — so intervals that merely touch on one calendar day do collide. The `zone_stalls_granted` of every gathered row is summed to give the stalls already in use, the zone's free stalls are its `stall_capacity` minus that sum but never below zero, and `zone_stalls_granted` for the new allocation is the smaller of `stalls_requested` and those free stalls.

Whatever the zone cannot cover is the unmet demand: `stalls_requested` minus `zone_stalls_granted`. When that unmet demand is zero, `overflow_stalls_granted` is 0 and the allocation is complete. When it is positive, the spill is only permitted if `allow_overflow` was supplied as true; otherwise the request is rejected with `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 409). If spill is permitted, the facility's shared overflow lot is drawn down the same way but across every zone of the facility: all allocations of the facility still in `ALLOCATED` status whose intervals overlap the requested one under the same closed-interval test are gathered, their `overflow_stalls_granted` are summed, and the free overflow stalls are the facility's `overflow_lot_stalls` minus that sum but never below zero. If the unmet demand exceeds those free overflow stalls, the request is rejected with `ERR_OVERFLOW_EXHAUSTED` (HTTP 409); otherwise `overflow_stalls_granted` is set to exactly the unmet demand. Allocations already in `RELEASED` status occupy nothing and are excluded from both sums.

Two derived figures are written on the granted row. `inclusive_days` is the difference between `end_date` and `start_date` in days, plus one, because the interval is closed — a one-day allocation has `inclusive_days` of 1. `overflow_surcharge_cents` is `overflow_stalls_granted` multiplied by the facility's `overflow_daily_surcharge_cents` and then by `inclusive_days`, which is 0 for any allocation that stayed entirely inside its zone. A granted allocation is created in `ALLOCATED` status; it raises the zone's `stalls_allocated` by `zone_stalls_granted` and recomputes the zone's `stalls_available`, raises the facility's `overflow_stalls_allocated` by `overflow_stalls_granted` and recomputes `overflow_stalls_available`, and raises the agreement's `fleet_stalls_allocated` by the sum of `zone_stalls_granted` and `overflow_stalls_granted`. The zone's `version`, the facility's `version` and the agreement's `version` each advance by 1.

Releasing a fleet allocation is the exact compensating action. From `ALLOCATED` the row moves to the terminal `RELEASED`, the zone's `stalls_allocated` falls by `zone_stalls_granted` with `stalls_available` recomputed, the facility's `overflow_stalls_allocated` falls by `overflow_stalls_granted` with `overflow_stalls_available` recomputed, and the agreement's `fleet_stalls_allocated` falls by the sum of the two grants. Both conserved stall totals return to exactly their pre-grant values, and the allocation's `version`, the zone's `version` and the facility's `version` each advance by 1.

### 3.5. Transaction-Day Reporting, the Audit Cycle, and Percentage Rent

Each month an operator declares what it did. A transaction-day report names the `agreement_id` it belongs to, identifies the period with `period_year` (which must lie between 2000 and 2100 inclusive) and `period_month` (1 through 12), and states two self-reported figures: `reported_gross_revenue_cents` and `reported_on_airport_transaction_days`, neither of which may be negative. A new report is created in `DRAFT` status with `submission_count` of 0, with `audited_gross_revenue_cents`, `audited_on_airport_transaction_days`, `revenue_variance_cents`, `audited_by_user_id` and `rejection_reason` all null, and with `variance_assessment_cents` and `period_rent_installment_cents` at 0.

An agreement may hold at most one report per `period_year` and `period_month` combination in any of the statuses `DRAFT`, `SUBMITTED`, `UNDER_AUDIT` or `REJECTED`; a second draft for a period already occupied by one of those is rejected with `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409). An already-`ACCEPTED` period is deliberately *not* blocked: amending a closed period is a legitimate audit outcome, and the amendment supersedes the earlier figure when it is itself accepted.

The report moves through a revision cycle. Submitting it carries `DRAFT → SUBMITTED`, requires the report to be in `DRAFT`, and additionally requires the owning agreement's `contract_status` to be either `ACTIVE` or `SUSPENDED` — a report cannot be submitted against an agreement that is still `DRAFT` or has already reached `EXPIRED` or `TERMINATED`. Each submission raises `submission_count` by 1, so a report that has been rejected and resubmitted carries a submission count above 1. An `AuditOfficer` opens the file with a begin-audit action, carrying `SUBMITTED → UNDER_AUDIT`. From `UNDER_AUDIT` the officer may reject, carrying `UNDER_AUDIT → REJECTED` and storing the supplied `rejection_reason` on the row, or accept. A rejected report is handed back to the operator, who reopens it, carrying `REJECTED → DRAFT` and clearing `rejection_reason` back to null; this closes the `DRAFT → SUBMITTED → UNDER_AUDIT → REJECTED → DRAFT` revision cycle, which may run any number of times. Every one of these transitions advances the report's `version` by 1.

Acceptance is the heaviest operation in the service, and it runs as a three-hop cascade. It requires the report to be in `UNDER_AUDIT` and requires both supplied figures — `audited_gross_revenue_cents` and `audited_on_airport_transaction_days` — to be at least 0. Before the cascade proper begins, there is a housekeeping step: if any *other* report of the same agreement, for the same `period_year` and `period_month`, is already in `ACCEPTED`, that earlier report is demoted `ACCEPTED → SUPERSEDED` — the terminal status for a displaced report — its own `version` advances by 1, and its contribution is subtracted from the agreement's `gross_revenue_ytd_cents`, `transaction_days_ytd` and `accepted_report_count` before anything is added back.

**Hop one** writes the audit onto the report itself. The two audited figures are stored; `revenue_variance_cents` is set to `audited_gross_revenue_cents` minus `reported_gross_revenue_cents`, which may be negative when the operator over-reported; `variance_assessment_cents` is the greater of zero and `revenue_variance_cents`, multiplied by the agreement's `percentage_rent_rate_bps`, divided by 10,000 and rounded half up — so an under-report is assessed at the agreement's own rent rate while an over-report attracts no assessment at all; `audited_by_user_id` is stamped with the accepting officer's `X-User-ID`; and the report's status becomes `ACCEPTED`.

**Hop two** rolls the accepted figures into the agreement's ledger and computes the rent installment. The agreement's `accepted_report_count` rises by 1, its `gross_revenue_ytd_cents` rises by `audited_gross_revenue_cents`, and its `transaction_days_ytd` rises by `audited_on_airport_transaction_days`. The rent computation then runs against those refreshed accumulators, and it has a shared preamble, two mutually exclusive variants, and a shared epilogue.

The preamble establishes three quantities. The number of months elapsed in the contract year is the agreement's `accepted_report_count` *after* hop two's increment. The monthly minimum guarantee is `mag_annual_cents` divided by 12 and truncated downward to a whole cent — a twelve-month contract year is the constant divisor here, so a guarantee of one million cents yields a monthly floor of 83,333 cents and the remainder is absorbed by the twelfth month. The minimum guarantee to date is the full `mag_annual_cents` once twelve or more months have elapsed, and otherwise the monthly minimum guarantee multiplied by the number of months elapsed. Year-to-date percentage rent is the agreement's `gross_revenue_ytd_cents` multiplied by `percentage_rent_rate_bps`, divided by 10,000, and rounded half up.

Under the `CUMULATIVE_YTD` variant, the rent due to date is the greater of the year-to-date percentage rent and the minimum guarantee to date, and the installment for this acceptance is that rent due to date minus the agreement's `rent_billed_to_date_cents` as it stood before this acceptance. Only the delta is charged, so a strong month absorbs the guarantee floor that a weak month would otherwise have triggered, and an installment may legitimately be zero or negative when a prior period over-billed relative to the year-to-date position.

Under the `MONTHLY_STANDALONE` variant, the month stands alone. The month's own percentage rent is this report's `audited_gross_revenue_cents` multiplied by `percentage_rent_rate_bps`, divided by 10,000 and rounded half up, and the installment is the greater of that month's percentage rent and the monthly minimum guarantee. Nothing is netted against what was billed before, so a weak month's guarantee floor is never recovered by a later strong month, and an agreement on this basis always ends the year with a `rent_billed_to_date_cents` strictly higher than the cumulative basis would have produced whenever any single month fell below the monthly floor.

The epilogue is identical for both variants. The agreement's `percentage_rent_accrued_cents` is set to the year-to-date percentage rent; its `rent_billed_to_date_cents` rises by the installment; its `last_installment_cents` is set to the installment; its `mag_shortfall_cents` is set to the greater of zero and the minimum guarantee to date minus the year-to-date percentage rent; and its `rent_tier` becomes `PERCENTAGE` when the year-to-date percentage rent is strictly greater than the minimum guarantee to date, and `MAG_FLOOR` otherwise. The installment is also written onto the report as `period_rent_installment_cents`. Only reports in `ACCEPTED` status feed any of these accumulators — reports sitting in `DRAFT`, `SUBMITTED`, `UNDER_AUDIT`, `REJECTED` or `SUPERSEDED` contribute nothing.

**Hop three** propagates the tier change outward. Because hop two moved the agreement's `rent_tier` from `MAG_FLOOR` to `PERCENTAGE`, every true-up settlement of that agreement still sitting in `DRAFT` is invalidated and moves `DRAFT → SUPERSEDED`, processed in ascending `created_at` order, each advancing its own `version` by 1. A settlement drafted against a minimum-guarantee assumption cannot survive the agreement crossing into percentage rent.

Two further consequences ride along with acceptance. When `variance_assessment_cents` came out greater than zero, the agreement's `compliance_status` moves to `COVENANT_BREACH`, from either `COMPLIANT` or `DELINQUENT`. And the acceptance advances the report's `version` by 1 and the agreement's `version` by 1.

### 3.6. Collecting the Customer Facility Charge and Filling the Trust

The Customer Facility Charge is billed per reporting period against a specific report. Raising a remittance names the `agreement_id` that owes it, the `report_id` whose transaction days the charge is derived from, and a `remittance_basis` of either `PROVISIONAL` or `FINAL`. Three referential guards apply, and they are evaluated in this order. First, duplication: at most one remittance may exist for a given `report_id` and `remittance_basis` pair in any status other than `RECONCILED`, and a second one is rejected with `ERR_DUPLICATE_REMITTANCE` (HTTP 409). Second, referential agreement: the report named by `report_id` must itself belong to the agreement named by `agreement_id` in the same body, and a cross-wired pair is rejected with `ERR_REPORT_AGREEMENT_MISMATCH` (HTTP 422). Third, basis admissibility: `PROVISIONAL` is only admissible while the report sits in `SUBMITTED` or `UNDER_AUDIT`, and `FINAL` is only admissible once the report has reached `ACCEPTED`; any other pairing is rejected with `ERR_REMITTANCE_BASIS_MISMATCH` (HTTP 422).

The billable quantity depends on the basis, and this is the whole point of having two. On the `PROVISIONAL` basis the billable transaction days are the report's `reported_on_airport_transaction_days` — the operator's own figure, billed before the audit confirms it, so that cash reaches the trust on schedule. On the `FINAL` basis the billable transaction days are the report's `audited_on_airport_transaction_days`. `expected_amount_cents` is the billable transaction days multiplied by the facility's `cfc_rate_per_transaction_day_cents`; the product is exact and no rounding occurs. The two bases therefore differ by exactly the difference between audited and reported days multiplied by that rate. A new remittance opens with `status` `PENDING`, `amount_received_cents` of 0, `shortfall_cents` equal to `expected_amount_cents`, and `allocated_to_debt_service_cents`, `allocated_to_om_cents`, `allocated_to_capital_cents` and `allocated_to_unallocated_cents` all at 0. Its `due_date` is the last calendar day of the month named by the report's `period_year` and `period_month`, advanced by the facility's `remittance_grace_days` days.

When the logical clock is moved past a `PENDING` remittance's `due_date`, the remittance moves `PENDING → DELINQUENT` and its agreement's `compliance_status` moves `COMPLIANT → DELINQUENT`; both rows advance their `version` by 1, and the sweep is counted in the clock response's `delinquent_remittance_count`.

Cash arrives through a treasury receipt, which supplies `amount_received_cents` — the new cents arriving in this call, not a running total. A receipt is accepted from `PENDING`, `DELINQUENT` or `RECEIVED`, and where it lands depends on the resulting cumulative position: when the already-received cents plus this call's cents remain strictly below `expected_amount_cents`, the remittance becomes `RECEIVED`; when they reach or exceed `expected_amount_cents`, it becomes the terminal `RECONCILED`. All five landing combinations are real: `PENDING → RECEIVED`, `PENDING → RECONCILED` on a first payment in full, `DELINQUENT → RECEIVED`, `DELINQUENT → RECONCILED`, and `RECEIVED → RECONCILED`. A remittance whose `expected_amount_cents` is zero reconciles on a receipt of zero and moves no cents through the trust at all.

Every receipt drives the same five-hop cascade. **Hop one** accumulates `amount_received_cents` on the remittance and recomputes `shortfall_cents` as the greater of zero and `expected_amount_cents` minus the cumulative `amount_received_cents`, so a reconciled remittance carries a `shortfall_cents` of 0. **Hop two** runs the trust waterfall over the newly arrived cents. **Hop three** recomputes the facility's `bond_coverage_status` from the moved buckets. **Hop four** offers the refreshed reserve to the debt-service auto-funding selector. **Hop five** releases capital projects that were waiting on the covenant. The remittance's `version` and the facility's `version` each advance by 1. Finally, if the receipt reconciled the last outstanding delinquency and no remittance of that agreement remains in `DELINQUENT`, the agreement's `compliance_status` returns `DELINQUENT → COMPLIANT`.

The waterfall itself is strictly ordered, and only the cents supplied in this one call flow through it — previously received cents are never re-run, and every bucket is read at its value as of the start of the request. Two gaps are measured first. The debt-service gap is the greater of zero and `ds_reserve_requirement_cents` minus `trust_debt_service_reserve_cents` minus `trust_debt_service_funded_cents`. The O&M gap is the greater of zero and `om_reserve_requirement_cents` minus `trust_om_reserve_cents`.

Bucket one is the debt-service reserve, and it behaves differently depending on the covenant posture at the start of the request. While `bond_coverage_status` is `DEFICIENT`, the whole receipt is swept toward debt service: the amount sent is the smaller of the arriving cents and the debt-service gap. While it is `SATISFIED`, only a share is swept: sixty percent of the arriving cents — that is, the arriving cents multiplied by 6,000 basis points, divided by 10,000 and truncated downward to a whole cent — capped at the debt-service gap. Bucket two is the O&M reserve, fed from whatever the first bucket left over: twenty-five percent of that residual — the residual multiplied by 2,500 basis points, divided by 10,000 and truncated downward — capped at the O&M gap. Bucket three is the capital fund, fed from whatever the second bucket left over, capped at the capital gap, which is the greater of zero and `capital_fund_cap_cents` minus `trust_capital_fund_cents`. Bucket four is residue: everything the capital bucket could not take.

Those four amounts are then added to `trust_debt_service_reserve_cents`, `trust_om_reserve_cents`, `trust_capital_fund_cents` and `trust_unallocated_cents` respectively, the whole receipt is added to `trust_lifetime_received_cents`, and the same four amounts accumulate on the remittance as `allocated_to_debt_service_cents`, `allocated_to_om_cents`, `allocated_to_capital_cents` and `allocated_to_unallocated_cents`. Because every share is truncated downward and the residue bucket absorbs whatever the earlier three declined, the four amounts always sum to exactly the cents supplied in the receipt: no cent is ever lost, and none is ever invented.

### 3.7. Bond Debt Service and the Coverage Test

A bond payment is scheduled by naming the `facility_id` whose trust will service it, a `series_label` such as "Series 2026A", the `due_date` on which it falls due, and `amount_due_cents`, which must be at least 1. The payload may also carry `coverage_requirement_bps`, the required coverage expressed in basis points of `amount_due_cents`; when omitted it defaults to 12500, meaning the trust must hold one and a quarter times the payment before the payment may be funded. A scheduled obligation opens in `SCHEDULED` status with `auto_funded` false, `funded_from_reserve_cents` of 0 and `coverage_ratio_at_funding` null.

The coverage test is the gate on every funding, and it is deliberately narrow about what counts as available cash. Only `trust_debt_service_reserve_cents` and `trust_unallocated_cents` are added together to form the available cents; `trust_debt_service_funded_cents`, `trust_om_reserve_cents`, `trust_capital_fund_cents`, `trust_encumbered_cents` and `trust_disbursed_cents` are all excluded. The test passes when the available cents multiplied by 10,000 is greater than or equal to the obligation's `coverage_requirement_bps` multiplied by its `amount_due_cents`. It is evaluated as exact integer arithmetic with no floating point anywhere, and the comparison is inclusive: available cash of exactly one and a quarter times the payment passes a 12500 basis-point requirement. Separately, and purely for display, `coverage_ratio_at_funding` records the available cents divided by `amount_due_cents`, rounded half up to four decimal places at the moment of funding; that display value never feeds the pass/fail test.

A treasury officer may fund a scheduled obligation explicitly. The obligation must be in `SCHEDULED`, and the coverage test must pass, or the request is rejected with `ERR_COVERAGE_BELOW_REQUIREMENT` (HTTP 409). On success `funded_from_reserve_cents` is set to `amount_due_cents`, `auto_funded` stays false, `coverage_ratio_at_funding` is recorded, `trust_debt_service_reserve_cents` falls by `amount_due_cents` while `trust_debt_service_funded_cents` rises by the same amount, and the facility's `funded_obligation_count` rises by 1. The obligation's `version` and the facility's `version` each advance by 1.

Funding also happens on its own, as hop four of a remittance receipt. That path runs only when `bond_coverage_status` came out `SATISFIED` after the waterfall. Among the facility's obligations still in `SCHEDULED`, the selector keeps those for which the coverage test passes; if none does, no obligation is funded and no error is raised, because a receipt is not a funding request. If at least one does, the selector orders the passing candidates by `due_date` ascending and breaks ties by `created_at` ascending, and funds exactly the first one — at most one obligation is funded per receive call, however much cash arrived. The effects are the same as an explicit funding except that `auto_funded` is set to true.

Whichever path funded it, an obligation reaching `FUNDED` raises `funded_obligation_count` and therefore releases capital projects, as §3.8 describes. Paying a funded obligation carries it `FUNDED → PAID`, its terminal status: `trust_debt_service_funded_cents` falls by `amount_due_cents`, `trust_disbursed_cents` rises by the same amount, `bond_coverage_status` is recomputed and may fall back to `DEFICIENT` because the funded bucket has just emptied, and the obligation's `version` and the facility's `version` each advance by 1. An obligation still `SCHEDULED` when the logical clock passes its `due_date` moves instead to the terminal `DEFERRED`, advancing its `version` by 1 and counting toward the clock response's `deferred_obligation_count`.

### 3.8. Capital Projects Funded by the CFC

A capital project is proposed by a `FacilityAdmin` against a `facility_id`, with a `project_name` and a `budget_cents` of at least 1, and optionally with a `predecessor_project_id` naming another project that must reach `CLOSED` before draws may be requested against this one. A project opens in `PROPOSED` status with `funding_hold` true and with `disbursed_cents`, `encumbered_cents`, `draw_request_count` and `rejected_draw_count` all at 0. Thereafter `disbursed_cents` is the total `amount_cents` over the project's `PAID` draws, `encumbered_cents` is the total `amount_cents` over its `AUTHORIZED` draws, `draw_request_count` counts every draw ever created against it, and `rejected_draw_count` counts those that reached `REJECTED`.

`funding_hold` is the covenant lock. Approving a proposed project carries it `PROPOSED → APPROVED` and evaluates that lock: `funding_hold` becomes false when the facility's `funded_obligation_count` is at least 1, and its `bond_coverage_status` is `SATISFIED`, and either `predecessor_project_id` is null or the predecessor project's status is `CLOSED`. When any of those three conditions fails, `funding_hold` stays true and the project waits in `APPROVED`. When `funding_hold` did become false, the project continues straight on `APPROVED → FUNDED` inside the same request, so an approval against a healthy trust returns a project already in `FUNDED`. Approval advances the project's `version` by 1.

A project left waiting in `APPROVED` is released later by whichever of three events clears its gate: the approval call itself, an obligation reaching `FUNDED`, or its predecessor reaching `CLOSED`. The release condition is the same in all three cases — status `APPROVED`, `funded_obligation_count` at least 1, `bond_coverage_status` `SATISFIED`, and the predecessor either absent or `CLOSED` — and the release sets `funding_hold` to false, moves the project `APPROVED → FUNDED`, and advances its `version` by 1. When an obligation reaches `FUNDED`, every eligible project of that facility is released, processed in ascending `created_at` order.

Closing a funded project carries it `FUNDED → CLOSED`, its terminal status, and requires `encumbered_cents` to be exactly 0; a project with money still tied up in authorised draws is rejected with `ERR_PROJECT_HAS_ENCUMBRANCE` (HTTP 409). Closing has a cascade of its own: every project whose `predecessor_project_id` names the closing project, and that sits in `APPROVED` with `funding_hold` true, is released to `FUNDED` provided the facility's `funded_obligation_count` is at least 1 and its `bond_coverage_status` is `SATISFIED`, processed in ascending `created_at` order. Cancelling is available from `PROPOSED`, from `APPROVED` and from `FUNDED`, landing in the terminal `CANCELLED`; cancelling from `APPROVED` or from `FUNDED` also requires `encumbered_cents` to be 0 and otherwise raises `ERR_PROJECT_HAS_ENCUMBRANCE`, while cancelling from `PROPOSED` has no encumbrance to check. Every one of these lifecycle actions advances the project's `version` by 1 and is reserved to `FacilityAdmin`.

Drawing on the capital bucket is a two-signature operation. A draw request names the `project_id` it funds and the `amount_cents` requested, which must be at least 1, may carry a free-text `memo` describing its purpose, and must carry `expected_project_version` as described in §2.9. Before the draw is created, the predecessor gate is checked at request time as well: when the project's `predecessor_project_id` is non-null and that predecessor is not in `CLOSED`, the request is rejected with `ERR_PREDECESSOR_NOT_CLOSED` (HTTP 409). A created draw opens in `REQUESTED` status with `requested_by_user_id` stamped from the caller's `X-User-ID` and `authorized_by_user_id` null, raises the project's `draw_request_count` by 1, and advances the project's `version` by 1.

From `REQUESTED` the draw forks into two branches whose side-effect sets diverge completely. The **authorising** branch is the money-moving one. It requires the draw to be in `REQUESTED`; it requires the acting `X-User-ID` to differ from `requested_by_user_id`, rejecting a self-authorisation with `ERR_SEGREGATION_OF_DUTIES`; it requires the project's status to be exactly `FUNDED`, rejecting anything else with `ERR_PROJECT_NOT_FUNDED` (HTTP 409); it requires the facility's `bond_coverage_status` to be `SATISFIED`, rejecting a deficient covenant with `ERR_BOND_COVENANT_DEFICIENT` (HTTP 409); it requires the project's `disbursed_cents` plus `encumbered_cents` plus this draw's `amount_cents` to be no greater than `budget_cents`, rejecting an overrun with `ERR_PROJECT_BUDGET_EXCEEDED` (HTTP 409); and it requires the facility's `trust_capital_fund_cents` to be at least `amount_cents`, rejecting a dry bucket with `ERR_CAPITAL_FUND_INSUFFICIENT` (HTTP 409). Those five business checks are evaluated in exactly that order. On success the draw moves to `AUTHORIZED`, `authorized_by_user_id` is stamped from `X-User-ID`, `trust_capital_fund_cents` falls by `amount_cents` while `trust_encumbered_cents` rises by the same amount, the project's `encumbered_cents` rises by `amount_cents`, and the draw's `version`, the project's `version` and the facility's `version` each advance by 1.

The **rejecting** branch touches no money at all. It requires the draw to be in `REQUESTED` and requires the acting `X-User-ID` to differ from `requested_by_user_id`, rejecting a self-rejection with `ERR_SEGREGATION_OF_DUTIES`; it imposes no project-status, covenant, budget or capital-fund condition. On success the draw moves to the terminal `REJECTED`, the project's `rejected_draw_count` rises by 1, not a single trust bucket moves, and the draw's `version` and the project's `version` each advance by 1. That absent bucket movement is the entire difference between the two branches.

An authorised draw is finished in one of two ways. Paying it carries `AUTHORIZED → PAID`, its terminal status: `trust_encumbered_cents` falls by `amount_cents` and `trust_disbursed_cents` rises by the same amount, the project's `encumbered_cents` falls by `amount_cents` and its `disbursed_cents` rises by the same amount, and the draw's `version`, the project's `version` and the facility's `version` each advance by 1. Voiding it carries `AUTHORIZED → VOIDED`, also terminal, and is the exact compensating action for authorisation: `trust_encumbered_cents` falls by `amount_cents` and `trust_capital_fund_cents` rises by the same amount, so the capital bucket returns to its pre-authorisation value and the trust's conservation identity is untouched; the project's `encumbered_cents` falls by `amount_cents`; and the draw's `version`, the project's `version` and the facility's `version` each advance by 1.

### 3.9. Allocating Shuttle Bus Operating Cost

The shuttle bus fleet that carries travellers between the terminals and the ConRAC is a shared cost, and it is divided among the operators once a month. A cost pool is opened with the `facility_id` it belongs to, the `period_year` and `period_month` it covers (the same 2000-to-2100 and 1-to-12 ranges as a transaction-day report), the `total_cost_cents` to be divided, which may not be negative, and an `allocation_basis` of either `TRANSACTION_DAYS` or `GROSS_REVENUE`. A pool opens in `OPEN` status with `total_basis_value`, `allocated_total_cents` and `line_count` all at 0.

Allocation is performed by a treasury officer and carries the pool `OPEN → ALLOCATED`, its terminal status. The candidate set is every agreement at the pool's facility whose `contract_status` is either `ACTIVE` or `SUSPENDED` and whose basis value for the period is greater than zero; agreements sitting in `DRAFT`, `TERMINATED` or `EXPIRED` are excluded even when they hold accepted reports for the period. An agreement's basis value is drawn strictly from its reports in `ACCEPTED` status whose `period_year` and `period_month` match the pool's exactly — reports in `DRAFT`, `SUBMITTED`, `UNDER_AUDIT`, `REJECTED` or `SUPERSEDED` contribute nothing. Under the `TRANSACTION_DAYS` basis the value is the total of `audited_on_airport_transaction_days` over that report set, so shuttle cost follows head-count of rentals and an operator with many low-value rentals pays more than its revenue would imply. Under the `GROSS_REVENUE` basis it is the total of `audited_gross_revenue_cents` over the same report set, so cost follows revenue instead; for identical report sets the two bases assign materially different amounts to the same agreement.

`total_basis_value` is the sum of the basis values across the candidate set. When the candidate set is empty or `total_basis_value` comes out as zero, the pool cannot be divided and the request is rejected with `ERR_NO_ALLOCATION_BASIS` (HTTP 422); the pool stays `OPEN`.

The division itself uses largest-remainder distribution, and **the rounding order is fixed**: floor first, then distribute. For each candidate the exact share is `total_cost_cents` multiplied by that agreement's basis value and divided by `total_basis_value`, kept as an exact rational; `floor_cents` is that exact share truncated downward to a whole cent, and the fractional part left over is remembered. The remainder pool is `total_cost_cents` minus the sum of every line's `floor_cents`. The lines are then ranked by fractional part descending, ties broken by the agreement's `created_at` ascending, and each line's one-based position in that ranking is stored as `remainder_rank`. A line's `amount_cents` is its `floor_cents` plus exactly one cent when its `remainder_rank` is less than or equal to the size of the remainder pool, and its `floor_cents` unchanged otherwise. Rounding each exact share to the nearest cent and summing is explicitly wrong here and will not reproduce `total_cost_cents`.

Each line also carries `basis_value`, the transaction days or gross revenue cents the agreement contributed, and `share_bps`, that basis value multiplied by 10,000, divided by `total_basis_value` and rounded half up. `share_bps` is a display figure only and is never used to compute money. Lines are created one per candidate agreement, in ascending `created_at` order of the agreements, and each carries the `shuttle_period_id` of the pool it draws from and the `agreement_id` it charges. They are immutable ledger rows: nothing ever mutates a line, and they are discoverable only by listing or reading them directly, because no other resource embeds them. On completion the pool's `total_basis_value` and `line_count` — the number of lines created — are written, `allocated_total_cents` is set to the sum of every line's `amount_cents`, which equals `total_cost_cents` exactly, and the pool's `version` advances by 1.

### 3.10. The Minimum Guarantee True-Up and Its Settlement

At the end of a contract year the airport authority reconciles what the operator actually owed against what it was billed. A settlement is drafted against an `agreement_id` and a `contract_year_index` of at least 1, which must equal the referenced agreement's own `contract_year_index`; a mismatch is rejected with `ERR_CONTRACT_YEAR_MISMATCH` (HTTP 422). At most one settlement per agreement and contract year may exist in `DRAFT`, `ISSUED` or `DISPUTED` at a time, and a second is rejected with `ERR_DUPLICATE_SETTLEMENT` (HTTP 409). A drafted settlement starts in `DRAFT` with `final_percentage_rent_cents`, `mag_cents`, `rent_billed_cents`, `audit_assessment_cents`, `base_true_up_cents`, `credit_bps`, `shuttle_credit_cents`, `net_true_up_cents` and `amount_paid_cents` all at 0, and `issued_by_user_id` null.

Issuance is what freezes the numbers, and it is available from `DRAFT` and again from `DISPUTED`. Both entries require the same two things. Every transaction-day report of the agreement must have reached `ACCEPTED` or `SUPERSEDED`; if any report of the agreement is still in `DRAFT`, `SUBMITTED`, `UNDER_AUDIT` or `REJECTED`, the issuance is rejected with `ERR_REPORTS_NOT_FINALIZED` (HTTP 409). And the acting `AuditOfficer`'s `X-User-ID` must not appear as `audited_by_user_id` on any `ACCEPTED` report of that agreement, as §2.10 describes; that segregation-of-duties check is evaluated before the reports-finalised check, so an officer who audited the year's reports is turned away with `ERR_SEGREGATION_OF_DUTIES` even when some report is also still open.

The computation runs in three pinned steps, and the order matters because the dependency looks circular but is not. **Step one** builds the base. `final_percentage_rent_cents` is the agreement's `gross_revenue_ytd_cents` multiplied by its `percentage_rent_rate_bps`, divided by 10,000 and rounded half up. `mag_cents` is the agreement's `mag_annual_cents`. `rent_billed_cents` is the agreement's `rent_billed_to_date_cents`. `audit_assessment_cents` is the total of `variance_assessment_cents` over the agreement's reports in `ACCEPTED` status only — a superseded report's assessment is excluded even though it was once real. All four are read from the agreement at issue time and frozen onto the settlement row. `base_true_up_cents` is then the greater of `mag_cents` and `final_percentage_rent_cents`, minus `rent_billed_cents`, plus `audit_assessment_cents`; it may come out negative when the year was over-billed.

**Step two** selects the shuttle performance credit, and the tier is keyed on `base_true_up_cents` and never on the net figure. When `base_true_up_cents` is zero or negative, `credit_bps` is 0. When it is at least fifty thousand dollars — five million cents — `credit_bps` is 300, a three percent credit. Otherwise, when it is at least ten thousand dollars — one million cents — `credit_bps` is 150, a one and a half percent credit. Below that threshold `credit_bps` is 0. `shuttle_credit_cents` is `base_true_up_cents` multiplied by `credit_bps`, divided by 10,000 and rounded half up. **Step three** is the netting: `net_true_up_cents` is `base_true_up_cents` minus `shuttle_credit_cents`. Keying the tier on `net_true_up_cents` is explicitly wrong.

Issuance stamps `issued_by_user_id` with the acting `X-User-ID`, carries the settlement to `ISSUED`, and advances its `version` by 1. Re-issuance from `DISPUTED` re-runs the whole computation against the agreement's current figures rather than reusing the frozen ones, so a settlement that was disputed and then re-issued after further audit activity carries fresh numbers.

The operator may push back. Disputing an issued settlement is the one action reserved exclusively to a `ConcessionaireOperator`; it carries `ISSUED → DISPUTED` and advances the settlement's `version` by 1, and re-issuance closes the `ISSUED → DISPUTED → ISSUED` negotiation loop, which may run any number of times. Settling is the treasury's closing act: it is available only from `ISSUED`, and the supplied `amount_paid_cents` must be at least `net_true_up_cents` or the request is rejected with `ERR_SETTLEMENT_UNDERPAID` (HTTP 422). On success `amount_paid_cents` is recorded, the settlement moves to the terminal `SETTLED`, the agreement's `compliance_status` returns from `COVENANT_BREACH` to `COMPLIANT` when it stood in `COVENANT_BREACH`, and the settlement's `version` and the agreement's `version` each advance by 1. The other terminal exit is `SUPERSEDED`, reached only when a report acceptance flips the agreement's `rent_tier` into `PERCENTAGE` while the settlement is still `DRAFT`.

## 4. Endpoint Definitions

All endpoints are mounted beneath `/rac`. An endpoint that brings a new resource into existence answers `201 Created`; every other successful call — reads, list queries, state-transition actions and the logical-clock capability — answers `200 OK`. Successful responses return the affected resource in `data`, except the list endpoints, which return an array, and the logical-clock endpoint, which returns its own summary object. The table below is an index only: request payloads, response side effects and the preconditions guarding each action are specified in the narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/rac/facilities` | Register a consolidated rental car facility with its CFC rate, reserve requirements and overflow lot | FacilityAdmin |
| GET | `/rac/facilities/{facility_id}` | Read one facility including the seven CFC trust buckets, the covenant posture and the logical clock | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/concessionaires` | Register a rental car brand operating in the ConRAC; the created id is the X-User-ID a ConcessionaireOperator acts as | FacilityAdmin |
| GET | `/rac/concessionaires/{concessionaire_id}` | Read one concessionaire | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/concessionaires` | List concessionaires, optionally filtered by facility | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/concession-agreements` | Draft a concession agreement carrying the minimum annual guarantee, the percentage rent rate and the rent settlement basis | FacilityAdmin |
| GET | `/rac/concession-agreements/{agreement_id}` | Read one concession agreement with both status axes and the full rent ledger | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/concession-agreements` | List concession agreements filtered by facility, concessionaire or either status axis | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/concession-agreements/{agreement_id}/execute` | Execute a drafted agreement: contract_status DRAFT -> ACTIVE | FacilityAdmin |
| POST | `/rac/concession-agreements/{agreement_id}/suspend` | Suspend an active agreement: contract_status ACTIVE -> SUSPENDED | FacilityAdmin |
| POST | `/rac/concession-agreements/{agreement_id}/reinstate` | Reinstate a suspended agreement: contract_status SUSPENDED -> ACTIVE, closing the suspend/reinstate loop | FacilityAdmin |
| POST | `/rac/counter-spaces` | Create a rental counter or ready/return space in the facility inventory | FacilityAdmin |
| GET | `/rac/counter-spaces/{counter_space_id}` | Read one counter or ready/return space | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/counter-spaces` | List counter/ready-return spaces filtered by facility or space class | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/counter-assignments` | Assign a counter/ready-return space to an agreement over a HALF-OPEN [start, end) interval; guarded by optimistic concurrency on the agreement's version | ConcessionaireOperator, FacilityAdmin |
| GET | `/rac/counter-assignments/{counter_assignment_id}` | Read one counter assignment | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/counter-assignments` | List counter assignments filtered by agreement, space or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/counter-assignments/{counter_assignment_id}/activate` | Occupy the space: ALLOCATED -> ACTIVE, only while the agreement's contract_status is ACTIVE | ConcessionaireOperator, FacilityAdmin |
| POST | `/rac/counter-assignments/{counter_assignment_id}/release` | Vacate the space: ALLOCATED or ACTIVE -> RELEASED | ConcessionaireOperator, FacilityAdmin |
| POST | `/rac/fleet-parking-zones` | Create a fleet parking zone with a fixed stall capacity | FacilityAdmin |
| GET | `/rac/fleet-parking-zones/{zone_id}` | Read one fleet parking zone with its live stall counters | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/fleet-parking-zones` | List fleet parking zones filtered by facility | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/fleet-allocations` | Allocate fleet parking stalls over a CLOSED [start, end] interval with optional overflow-lot spill; guarded by optimistic concurrency on the zone's version | ConcessionaireOperator, FacilityAdmin |
| GET | `/rac/fleet-allocations/{fleet_allocation_id}` | Read one fleet allocation with its zone/overflow split and surcharge | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/fleet-allocations` | List fleet allocations filtered by agreement, zone or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/fleet-allocations/{fleet_allocation_id}/release` | Release the allocation: ALLOCATED -> RELEASED, returning both zone stalls and overflow stalls | ConcessionaireOperator, FacilityAdmin |
| POST | `/rac/transaction-day-reports` | Draft a monthly transaction-day and gross-revenue report for an agreement | ConcessionaireOperator, FacilityAdmin |
| GET | `/rac/transaction-day-reports/{report_id}` | Read one transaction-day report with its audited figures and variance assessment | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/transaction-day-reports` | List transaction-day reports filtered by agreement, status or reporting period | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/transaction-day-reports/{report_id}/submit` | Submit the report for audit: DRAFT -> SUBMITTED | ConcessionaireOperator, FacilityAdmin |
| POST | `/rac/transaction-day-reports/{report_id}/begin-audit` | Open the audit: SUBMITTED -> UNDER_AUDIT | AuditOfficer |
| POST | `/rac/transaction-day-reports/{report_id}/accept` | Accept audited figures: UNDER_AUDIT -> ACCEPTED, driving the three-hop rent-ledger cascade | AuditOfficer |
| POST | `/rac/transaction-day-reports/{report_id}/reject` | Reject the report: UNDER_AUDIT -> REJECTED | AuditOfficer |
| POST | `/rac/transaction-day-reports/{report_id}/reopen` | Reopen a rejected report for revision: REJECTED -> DRAFT, closing the revision cycle | ConcessionaireOperator, FacilityAdmin |
| POST | `/rac/cfc-remittances` | Raise a Customer Facility Charge remittance for a reporting period on either the PROVISIONAL or the FINAL transaction-day basis | ConcessionaireOperator, FacilityAdmin |
| GET | `/rac/cfc-remittances/{remittance_id}` | Read one CFC remittance with its waterfall split | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/cfc-remittances` | List CFC remittances filtered by agreement, report or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/cfc-remittances/{remittance_id}/receive` | Record CFC cash into the trust, driving the five-hop waterfall / covenant / auto-funding / project-release cascade | FinanceOfficer |
| POST | `/rac/debt-service-obligations` | Schedule a bond debt-service payment to be funded from the CFC trust | FacilityAdmin, FinanceOfficer |
| GET | `/rac/debt-service-obligations/{obligation_id}` | Read one debt-service obligation | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/debt-service-obligations` | List debt-service obligations filtered by facility or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/debt-service-obligations/{obligation_id}/fund` | Explicitly fund a scheduled obligation once the coverage test passes: SCHEDULED -> FUNDED | FinanceOfficer |
| POST | `/rac/debt-service-obligations/{obligation_id}/pay` | Pay a funded obligation out of the trust: FUNDED -> PAID | FinanceOfficer |
| POST | `/rac/shuttle-cost-periods` | Open a monthly shuttle bus operating cost pool on a chosen allocation basis | FacilityAdmin, FinanceOfficer |
| GET | `/rac/shuttle-cost-periods/{shuttle_period_id}` | Read one shuttle cost period | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/shuttle-cost-periods` | List shuttle cost periods filtered by facility or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/shuttle-cost-periods/{shuttle_period_id}/allocate` | Allocate the shuttle cost pool across eligible agreements by largest remainder: OPEN -> ALLOCATED | FinanceOfficer |
| GET | `/rac/shuttle-cost-allocations/{shuttle_allocation_id}` | Read one immutable shuttle cost allocation line | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/shuttle-cost-allocations` | List shuttle cost allocation lines filtered by period or agreement; the only discovery channel for these cascade-created rows | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/capital-projects` | Propose a capital project funded from the CFC capital bucket, optionally gated behind a predecessor project | FacilityAdmin |
| GET | `/rac/capital-projects/{project_id}` | Read one capital project | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/capital-projects` | List capital projects filtered by facility, predecessor or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/capital-projects/{project_id}/approve` | Approve a proposed project: PROPOSED -> APPROVED, continuing straight to FUNDED when the covenant and predecessor gates are already clear | FacilityAdmin |
| POST | `/rac/capital-projects/{project_id}/close` | Close a funded project with no outstanding encumbrance: FUNDED -> CLOSED, releasing any successor projects waiting on this predecessor | FacilityAdmin |
| POST | `/rac/capital-projects/{project_id}/cancel` | Cancel a project from PROPOSED, APPROVED or FUNDED when nothing is encumbered | FacilityAdmin |
| POST | `/rac/capital-disbursements` | Request a capital draw against a project; guarded by optimistic concurrency on the project's version and by the predecessor gate | FinanceOfficer, FacilityAdmin |
| GET | `/rac/capital-disbursements/{disbursement_id}` | Read one capital draw | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/capital-disbursements` | List capital draws filtered by project or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/capital-disbursements/{disbursement_id}/authorize` | Authorize a draw: REQUESTED -> AUTHORIZED; the requester may not authorize their own draw | FinanceOfficer |
| POST | `/rac/capital-disbursements/{disbursement_id}/reject` | Reject a draw: REQUESTED -> REJECTED; the money-free branch of the fork | FinanceOfficer |
| POST | `/rac/capital-disbursements/{disbursement_id}/pay` | Pay an authorized draw out of the trust: AUTHORIZED -> PAID | FinanceOfficer |
| POST | `/rac/capital-disbursements/{disbursement_id}/void` | Void an authorized draw: AUTHORIZED -> VOIDED, returning the encumbrance to the capital bucket | FinanceOfficer |
| POST | `/rac/true-up-settlements` | Draft a minimum-guarantee true-up settlement for a contract year | AuditOfficer, FacilityAdmin |
| GET | `/rac/true-up-settlements/{settlement_id}` | Read one true-up settlement with the frozen base / credit / net figures | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| GET | `/rac/true-up-settlements` | List true-up settlements filtered by agreement or status | FacilityAdmin, ConcessionaireOperator, AuditOfficer, FinanceOfficer |
| POST | `/rac/true-up-settlements/{settlement_id}/issue` | Issue the settlement from DRAFT or DISPUTED, freezing the true-up computation; the officer who audited the year's reports may not issue it | AuditOfficer |
| POST | `/rac/true-up-settlements/{settlement_id}/dispute` | Dispute an issued settlement: ISSUED -> DISPUTED, reopening the negotiation loop | ConcessionaireOperator |
| POST | `/rac/true-up-settlements/{settlement_id}/settle` | Settle an issued true-up: ISSUED -> SETTLED once the payment covers net_true_up_cents | FinanceOfficer |
| POST | `/rac/_clock/set_current_utc` | Move the server's logical clock. Before any call the clock reads exactly 2026-08-01T00:00:00Z and never falls back to real wall-clock time. Advancing the clock past a PENDING remittance's due_date marks it DELINQUENT, past a SCHEDULED obligation's due_date marks it DEFERRED, and past an agreement's term_end_date expires or terminates it. | FacilityAdmin |

## 5. Error Code Catalogue

Every error response carries the envelope of §2.2 with `response_type` set to `error` and the identifier below in `data.error_id`. The conditions that raise each code are stated in the §2 contracts and the §3 narratives that own them; the order in which competing conditions are evaluated is the admission ladder of §2.6.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_CONCESSIONAIRE_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_COUNTER_SPACE_NOT_FOUND` | 404 |
| `ERR_COUNTER_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_FLEET_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_OBLIGATION_NOT_FOUND` | 404 |
| `ERR_SHUTTLE_PERIOD_NOT_FOUND` | 404 |
| `ERR_SHUTTLE_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_NOT_FUNDED` | 409 |
| `ERR_PROJECT_HAS_ENCUMBRANCE` | 409 |
| `ERR_BOND_COVENANT_DEFICIENT` | 409 |
| `ERR_PREDECESSOR_NOT_CLOSED` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_OUTSIDE_AGREEMENT_TERM` | 422 |
| `ERR_COUNTER_SPACE_OCCUPIED` | 409 |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 |
| `ERR_OVERFLOW_EXHAUSTED` | 409 |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 |
| `ERR_DUPLICATE_BRAND_CODE` | 409 |
| `ERR_DUPLICATE_SPACE_LABEL` | 409 |
| `ERR_DUPLICATE_REMITTANCE` | 409 |
| `ERR_DUPLICATE_SETTLEMENT` | 409 |
| `ERR_REPORT_AGREEMENT_MISMATCH` | 422 |
| `ERR_REMITTANCE_BASIS_MISMATCH` | 422 |
| `ERR_CONTRACT_YEAR_MISMATCH` | 422 |
| `ERR_REPORTS_NOT_FINALIZED` | 409 |
| `ERR_NO_ALLOCATION_BASIS` | 422 |
| `ERR_COVERAGE_BELOW_REQUIREMENT` | 409 |
| `ERR_PROJECT_BUDGET_EXCEEDED` | 409 |
| `ERR_CAPITAL_FUND_INSUFFICIENT` | 409 |
| `ERR_SETTLEMENT_UNDERPAID` | 422 |
