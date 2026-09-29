# County Land Bank Authority API — Product Requirements Document

## 1. Introduction

A county land bank authority exists to break the cycle in which tax-delinquent, vacant and structurally failing parcels pass from one absentee owner to the next, each transfer deepening the blight and shrinking the tax base. This document specifies the API that runs such an authority end to end: taking parcels in through tax foreclosure, donation or negotiated purchase; clearing the clouded titles those channels leave behind; holding, securing, mowing and demolishing the inventory while the money lasts; and putting parcels back into productive private hands through four distinct disposition programs, each with its own price floor, eligibility bar and reuse expectation.

Two pressures shape almost every rule below. The first is fiscal: the authority spends restricted grant, tax-increment recapture and general-fund money, and every dollar committed to an acquisition, a mowing order or a demolition run must be traceable, releasable and never double-spent. The second is stewardship: a parcel conveyed to a buyer who never performs must come back, which means performance deadlines, cure periods and reverter deeds are first-class objects rather than paperwork. Buyers who owe the county delinquent taxes, who carry open code-enforcement violations, or who have already had a deed reverted are barred from acquiring more inventory, and the system computes that bar from live county data rather than from a self-declaration.

The API is mounted under `/land-bank`. Every temporal rule in this specification — expiries, deadlines, work windows, hearing freshness, holding terms — is evaluated against a server-held logical clock rather than wall-clock time, so that an entire multi-year blight-elimination cycle can be driven deterministically in a test harness.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent, or if `X-User-Role` is not one of the six roles the authority recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

The six roles are:

- `IntakeOfficer` — acquisition and title staff. Registers parcels, posts code-enforcement snapshots, records owners of record and the parcel adjacency graph, runs acquisition packets and clears title.
- `BoardClerk` — clerk to the board of directors. Authorizes funding sources, board-approves acquisition packets, records board decisions on disposition applications and executes development agreements.
- `DispositionOfficer` — disposition program staff. Lists inventory parcels, holds community reuse hearings, registers applicants, screens buyers, requests further information and recommends awards.
- `InventoryManager` — inventory operations. Registers contractors, schedules and settles securing, mowing and demolition work, plans and executes demolition prioritization runs, and runs the periodic compliance sweep.
- `CountyTreasurer` — posts tax roll delinquency balances, books tax-increment recapture receipts and audits the funding ledger.
- `Applicant` — a prospective buyer or developer acting on its own applications and development agreements.

For the five staff roles — `IntakeOfficer`, `BoardClerk`, `DispositionOfficer`, `InventoryManager` and `CountyTreasurer` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where an audit trail is required (as `initiated_by_user_id` and `closed_by_user_id` on an acquisition packet, `recorded_by_user_id` on an adjacency edge, `screened_by_user_id` on an eligibility screening, and `recommended_by_user_id` and `decided_by_user_id` on a disposition application), and it compares recorded operator identifiers against each other to enforce segregation of duties, but it never compares an opaque identifier to any entity's `id`.

When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting applicant record. Ownership is checked against that value: submitting or resubmitting an application requires `X-User-ID` to equal the application's `applicant_id`; reporting milestone completions requires `X-User-ID` to equal the `applicant_id` of the agreement's originating application; and when an `Applicant` drafts a new application, the `applicant_id` in the payload must be its own. Any mismatch is rejected with `ERR_NOT_APPLICATION_OWNER` (403).

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10 and must be between 1 and 100 inclusive. `offset` skips a number of leading records; it defaults to 0 and must not be negative. A `limit` outside its range or a negative `offset` is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific list states otherwise, records are returned sorted by `created_at` ascending. Four lists declare their own order: title actions on a parcel come oldest first, reuse hearings on a parcel come newest `hearing_at` first, the demolition runs drawn against a funding source come in ascending `run_sequence`, and the eligibility screenings of an application come in ascending `sequence_no`.

Every list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope.

Lists also accept filters drawn from the fields of the resource being listed. Parcels may be filtered by `custody_status`, `title_status`, `situs_ward` and `owner_of_record_applicant_id`; acquisition packets by `property_id`, `funding_source_id` and `status`; title actions by `status`; maintenance orders by `property_id`, `contractor_id`, `funding_source_id`, `demolition_run_id`, `status` and `work_type`; demolition runs by `status`; disposition applications by `property_id`, `applicant_id`, `status` and `program`; eligibility screenings by `outcome`; development agreements by `application_id`, `property_id` and `status`; and the authority-wide summary read by `situs_ward`.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Parcels, funding sources, acquisition packets, title actions, contractors, maintenance orders, demolition runs, applicants, disposition applications and development agreements all carry the same four system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped when the record is first written.
- `updated_at` — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the record, including mutations the server performs on its own initiative through a cascade.
- `version` — an integer that starts at 1 and increases by exactly 1 on each mutation of that record. Derived-field refreshes count as mutations: recomputing a parcel's blight score or a funding source's ledger position bumps that record's `version` and `updated_at`.

Three record types are append-only observations rather than living records, and they carry only `id` and `created_at` — they have no `updated_at` and no `version` at all: adjacency edges between parcels, community reuse hearings, and eligibility screenings.

Every instant a response carries is spelled the same way as `created_at`, whether the server stamped it or the caller supplied it. The business instants — among them `expires_on`, `filed_at`, `adjudicated_at`, `acquired_at`, `listed_at`, `last_mow_at`, `demolished_at`, `license_expires_on`, `window_start`, `window_end`, `completed_at`, `hearing_at`, `submitted_at`, `screened_at`, `board_decision_at`, `executed_at`, `performance_deadline`, `cure_deadline`, `complied_at`, `reverted_at`, `last_reverter_at`, the sweep's `swept_at` and the clock's own `current_utc` — are all rendered as ISO 8601 UTC timestamps with exactly three fractional digits and a trailing `Z`. An instant the caller supplied in a request body is therefore echoed back in that normalized spelling rather than verbatim: an offset is converted to UTC, and a fractional part finer than a millisecond is truncated to three digits in the rendering. An instant-valued field that holds no value is rendered as null.

The server holds a logical UTC clock which starts at the fixed default `2026-08-01T00:00:00Z` and is never derived from wall-clock time. An administrative test-driving capability moves it: the caller supplies the target instant as `to_iso8601` and the server answers with the resulting `current_utc`. Setting the clock mutates no entity and triggers no sweep. Every rule in this document that speaks of "the current instant" — expiry, performance and cure deadlines, work windows, hearing freshness, holding terms, the reverter lookback — reads this clock.

### 2.5. Left-to-Right Resolution of Paths and Payload References

Identifiers in a request path are resolved strictly left to right, and the first one that matches no record ends the request with a 404 naming that resource: an unknown parcel yields `ERR_PROPERTY_NOT_FOUND`, an unknown acquisition packet `ERR_PACKET_NOT_FOUND`, an unknown title action `ERR_TITLE_ACTION_NOT_FOUND`, an unknown maintenance order `ERR_ORDER_NOT_FOUND`, an unknown demolition run `ERR_RUN_NOT_FOUND`, an unknown disposition application `ERR_APPLICATION_NOT_FOUND`, an unknown development agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown applicant `ERR_APPLICANT_NOT_FOUND` and an unknown funding source `ERR_FUNDING_SOURCE_NOT_FOUND`.

References carried in a request body are resolved the same way and produce the same codes: `property_id` and `adjacent_property_id` resolve to a parcel (`ERR_PROPERTY_NOT_FOUND`), `applicant_id` to an applicant (`ERR_APPLICANT_NOT_FOUND`), `contractor_id` to a contractor (`ERR_CONTRACTOR_NOT_FOUND`), `funding_source_id` to a funding source (`ERR_FUNDING_SOURCE_NOT_FOUND`) and `application_id` to a disposition application (`ERR_APPLICATION_NOT_FOUND`). Body-reference resolution applies when opening an acquisition packet, scheduling a maintenance order, planning a demolition run, recording an adjacency edge, recording an owner of record, drafting a disposition application and executing a development agreement.

### 2.6. The Two Parallel Dimensions of a Parcel

Every parcel record carries two independent lifecycle dimensions that advance on their own schedules, and rules in each dimension frequently read the other.

The **custody dimension**, `custody_status`, begins at `PROSPECT` — a registry-only parcel the authority has catalogued but does not own. Closing an acquisition moves it to `ACQUIRED`; listing it for disposition moves it to `LISTED`; executing a development agreement moves it to `CONVEYED`; enforcing a reverter moves it to `REVERTED`; and a reverted parcel with freshly cleared title can be listed again, so the cycle `CONVEYED → REVERTED → LISTED` re-enters disposition. No custody value is terminal.

The **title dimension**, `title_status`, begins at `CLOUDED`. Filing a title action moves it to `QUIET_TITLE_FILED`; an adjudication that clears the defects moves it to `CLEAR`; an adjudication that finds defects remaining returns it to `CLOUDED` so another round can be filed, giving the cycle `QUIET_TITLE_FILED → CLOUDED → QUIET_TITLE_FILED`; and a reverter deed re-clouds a `CLEAR` title, taking it directly back to `CLOUDED`. No title value is terminal either.

Because the dimensions are independent, a parcel may be `ACQUIRED` with `CLOUDED` title, or `REVERTED` with `CLEAR` title. Where one dimension gates the other, this document says so explicitly.

### 2.7. Money, Scores and Rounding

All monetary amounts in this system are integer cents; there are no fractional cents anywhere in a request or a response. Wherever a rounding step is required, the method is **round half up**, and each calculation below pins the exact points at which rounding occurs. Two calculations are deliberately multi-stage: the maintenance-order estimate rounds each line item to whole cents before summing them and then rounds the county overhead once against that sum, and the demolition-run allocation floors the provisional cap before selection and rounds the administrative fee after selection. Summing at full precision and rounding once at the end is not the rule and produces different cents.

Two non-monetary quantities also round: a parcel's blight score is carried at full precision through its terms and rounded half up to one decimal place exactly once at the end, and a hearing's support ratio is rounded half up to four decimal places.

### 2.8. The Conserved Funding Ledger

A funding source is the authority's budget envelope, and its ledger is derived — never set directly by a caller. `committed_cents` is the sum of three open commitment classes on that source: the `committed_cents` of every acquisition packet in `BOARD_APPROVED`, the `estimated_cost_cents` of every maintenance order in `SCHEDULED`, and the `admin_fee_cents` of every demolition run in `EXECUTED`. `disbursed_cents` is the sum of the settled outflows: for every packet in `CLOSED`, its `offer_price_cents` plus its `title_search_fee_cents`, and for every maintenance order in `COMPLETED`, its `actual_cost_cents`. Cancelled orders and declined packets contribute to neither sum. `authorized_cents` is the original authorization plus everything recaptured into `recaptured_cents`, and `available_cents` is `authorized_cents` less `committed_cents` less `disbursed_cents`. The identity that authorized money always equals available plus committed plus disbursed money holds before and after every operation in this specification; each compensating pair — approve/decline, schedule/cancel, commit/disburse — restores it exactly.

A reserve floor protects the tail of each authorization. `reserve_floor_cents` is 5 percent of `authorized_cents`, rounded half up, and it is recomputed whenever the authorization changes. Whenever a commitment leaves `available_cents` strictly below `reserve_floor_cents`, the source moves `ACTIVE → CONSTRAINED`, and that transition immediately parks every acquisition packet on the source that is still in `DUE_DILIGENCE`: each moves `DUE_DILIGENCE → ON_HOLD_FUNDING` with `hold_reason` set to `FUNDING_SOURCE_CONSTRAINED`. Whenever a release lifts `available_cents` back to at least `reserve_floor_cents`, the source moves `CONSTRAINED → ACTIVE` and every packet on it in `ON_HOLD_FUNDING` moves `ON_HOLD_FUNDING → DUE_DILIGENCE` with `hold_reason` cleared to null. Each of these automatic moves is a mutation of the affected record and bumps its `version`.

`EXPIRED` is the one terminal funding state, reached only through the compliance sweep. An expired source may take no further commitment, and a maintenance order it funds may no longer be completed. Packets already sitting in `ON_HOLD_FUNDING` on a source that expires stay exactly where they are; the sweep does not release them.

Spending restrictions are enforced against the kind of spend, not the amount. A source whose `restriction` is `ACQUISITION_ONLY` refuses maintenance orders and demolition runs; a source whose `restriction` is `DEMOLITION_ONLY` refuses acquisition packets and refuses any maintenance order whose `work_type` is not `DEMOLITION`; a source whose `restriction` is `ANY` admits every category. A restriction breach is reported as `ERR_FUNDING_RESTRICTION_VIOLATION`.

### 2.9. Optimistic Concurrency on Parcels and Funding Sources

Two write operations act on a picture of a parent record that the client must prove it has actually seen, because neither is blocked by a state precondition: a parcel may legitimately carry several maintenance orders of different work types and windows, and a funding source may legitimately carry several planned demolition runs, each a separate slice of the budget. Optimistic concurrency on the parent's `version` is therefore the only signal that the client planned against a stale view.

Scheduling a maintenance order on a parcel requires `expected_property_version` in the request body. The field is not optional. If its value differs from the parcel's current `version` — and code-violation reports, tax roll postings, order completions, adjacency recordings and every cascade in this document advance that `version` — the request is rejected with `ERR_STALE_PROPERTY_VERSION` (412) and nothing is written.

Planning a demolition run requires `expected_funding_source_version` in the request body, likewise non-optional. If its value differs from the funding source's current `version`, the request is rejected with `ERR_STALE_FUNDING_SOURCE_VERSION` (412), so a run can never be planned against a budget picture that has already moved.

No other endpoint in this API takes a version field, and no other endpoint performs a version check.

### 2.10. Segregation of Duties

Two decisions may not be made twice by the same person. Closing an acquisition packet requires the acting `X-User-ID` to differ from the packet's `initiated_by_user_id`, so the officer who opened a file cannot also sign the deed into inventory. Recommending a disposition application requires the acting `X-User-ID` to differ from the `screened_by_user_id` of the governing eligibility screening — the screening on that application with the greatest `sequence_no` — so the officer who cleared a buyer cannot also carry that buyer to the board. Either violation is reported as `ERR_SEGREGATION_OF_DUTIES` (403).

### 2.11. Conserved Inventory Area

The authority's land holding is a conserved quantity, reported by the authority-wide summary read. `inventory_area_sqft` is the sum of `lot_area_sqft` over every parcel whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`; `conveyed_area_sqft` is the same sum over parcels in `CONVEYED`; and `inventory_property_count` is the number of parcels in the three inventory states. Registry-only `PROSPECT` parcels are counted in neither sum. Both figures are integer square feet with no rounding.

Conveyance and reverter form an exact compensating pair on this quantity: executing a development agreement removes precisely the parcel's `lot_area_sqft` from the inventory area and adds it to the conveyed area, and enforcing the reverter returns precisely the same `lot_area_sqft`, so the inventory area after a reverter equals its value before the conveyance that preceded it.

### 2.12. Order of Validation

When several rules could reject one request, the earliest rule in the following ladder decides the response, so that the reported cause is the real one:

1. Header presence and role recognition (`ERR_UNAUTHENTICATED`), then endpoint role authorization (`ERR_ROLE_NOT_PERMITTED`), then applicant ownership on the applicant-driven operations (`ERR_NOT_APPLICATION_OWNER`).
2. Request shape: required fields, enum membership, numeric ranges and the conditional-required pairings — `openings_count` present exactly when `work_type` is `SECURE`, `foreclosure_case_no` present exactly when `channel` is `TAX_FORECLOSURE`, `donor_name` present exactly when `channel` is `DONATION`, `offer_price_cents` exactly zero when `channel` is `DONATION`, `support_count` no greater than `comment_count`, `defect_count` at least 1 exactly when `outcome` is `DEFECT_REMAINS`, `limit` within 1 to 100 and `offset` not negative. All of these are `ERR_INVALID_REQUEST`. Two neighbouring constraints are deliberately *not* folded into this rule and keep their own codes: work-window ordering (`ERR_WINDOW_INVALID`, evaluated immediately after this step) and the abatement-year cap (`ERR_ABATEMENT_YEARS_EXCEED_CAP`, evaluated far later, among the agreement rules).
3. Registry uniqueness and adjacency shape: duplicate `parcel_id` (`ERR_PARCEL_ID_DUPLICATE`), an edge from a parcel to itself (`ERR_SELF_ADJACENCY`), then a duplicate unordered pair (`ERR_ADJACENCY_DUPLICATE`).
4. Existence of path identifiers, then existence of body references (the 404 family of §2.5).
5. Optimistic concurrency (`ERR_STALE_PROPERTY_VERSION`, `ERR_STALE_FUNDING_SOURCE_VERSION`).
6. Agreement uniqueness — at most one development agreement per application (`ERR_AGREEMENT_ALREADY_EXISTS`). This test deliberately outranks the state and custody tests that follow it: executing the first agreement moves the application to `AWARDED` and the parcel to `CONVEYED`, so a replayed execution would otherwise surface a misleading state error instead of naming the real cause.
7. State of the target record against the from-state its transition declares (`ERR_PACKET_INVALID_STATE`, `ERR_TITLE_ACTION_ALREADY_ADJUDICATED`, `ERR_ORDER_NOT_SCHEDULED`, `ERR_APPLICATION_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_RUN_NOT_PLANNED`), followed by the cross-entity state guards in this order: parcel not in inventory (`ERR_PROPERTY_NOT_IN_INVENTORY`), an already-open title action (`ERR_TITLE_ACTION_OPEN`), title not clear (`ERR_TITLE_NOT_CLEAR`), parcel not listed (`ERR_PROPERTY_NOT_LISTED`), funding source expired (`ERR_FUNDING_SOURCE_EXPIRED`), and a governing screening that did not pass (`ERR_APPLICATION_INVALID_STATE`).
8. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
9. Statutory buyer exclusions and contractor fitness: `ERR_APPLICANT_TAX_DELINQUENT`, then `ERR_APPLICANT_CODE_VIOLATOR`, then `ERR_CONTRACTOR_DEBARRED`.
10. Programme pairing and referential fitness: `ERR_APPLICANT_TYPE_NOT_ELIGIBLE`, then `ERR_NONPROFIT_REGISTRATION_REQUIRED`, then `ERR_SIDE_LOT_REQUIRES_VACANT`, then `ERR_NOT_ADJACENT_OWNER`, then `ERR_CONTRACTOR_SPECIALTY_MISMATCH`.
11. Temporal fitness: `ERR_HEARING_STALE`, then `ERR_HEARING_SUPPORT_INSUFFICIENT`, then `ERR_CONTRACTOR_LICENSE_EXPIRED`, then `ERR_DEADLINE_IN_PAST`, then `ERR_ABATEMENT_YEARS_EXCEED_CAP`.
12. Interval and aggregate constraints: `ERR_PROPERTY_WINDOW_CONFLICT`, then `ERR_DEMOLITION_BUFFER_VIOLATION`, then `ERR_CONTRACTOR_CAPACITY_EXCEEDED`, then `ERR_DEMOLITION_REQUIRES_STRUCTURE`, then `ERR_OFFER_BELOW_QUOTE`, then `ERR_REVISION_LIMIT_EXCEEDED`, then `ERR_HOMEOWNER_LIMIT_EXCEEDED`, then `ERR_MILESTONE_OVERFLOW`, then `ERR_EMPTY_RUN`.
13. Fiscal capacity, last of all: `ERR_FUNDING_RESTRICTION_VIOLATION`, then `ERR_FUNDING_CONSTRAINED`, then `ERR_RUN_BUDGET_EXCEEDS_AVAILABLE`, then `ERR_FUNDING_INSUFFICIENT`.

## 3. Business Logic & Workflows

### 3.1. Building the Parcel Registry

An `IntakeOfficer` catalogues a parcel long before the authority owns it. Registration records the county assessor's parcel number as `parcel_id`, which must be unique across the registry and must read as the letters `APN`, a hyphen, and then four to eight digits; a second registration of the same number is refused with `ERR_PARCEL_ID_DUPLICATE`. The rest of the intake payload is the physical picture of the parcel: its situs street address as `address` (1 to 200 characters), the county ward it sits in as `situs_ward` (an integer from 1 to 9), its `lot_area_sqft` (at least 100 square feet), the county's `assessed_value_cents` (zero or more), the boolean `structure_present`, the `structure_condition_grade` — one of `A`, `B`, `C`, `D` or `F` — and `vacancy_months`, the number of whole months the parcel has stood vacant, which may be zero but never negative.

A newly registered parcel enters custody `PROSPECT` and title `CLOUDED`. Its `secured` flag is false; its `nuisance_complaint_count`, `open_code_violation_count`, `delinquent_tax_balance_cents`, `pre_acquisition_delinquency_cents` and `acquisition_cost_cents` are all zero; its `current_blight_score` is zero; and `intake_blight_score`, `acquisition_channel`, `acquired_at`, `last_mow_at`, `demolished_at`, `listed_at` and `owner_of_record_applicant_id` are all null. The provisional intake score is deliberately left null at registration: it is stamped exactly once, when an acquisition closes.

Three county data feeds keep the registry honest, and each is the only way its fields move. An `IntakeOfficer` posts the code-enforcement snapshot, supplying `open_code_violation_count` and `nuisance_complaint_count`, which overwrite the stored values outright; the parcel's `current_blight_score` is then recomputed, while `intake_blight_score` is never touched again. A `CountyTreasurer` posts the tax roll, supplying `delinquent_tax_balance_cents` together with the `tax_year` the posting belongs to; when the parcel has an `owner_of_record_applicant_id`, that applicant's delinquency roll-up and eligibility standing are recomputed on the spot. An `IntakeOfficer` also records the private owner of record by supplying an `applicant_id`; this is permitted only while the parcel is still `PROSPECT`, since ownership of land bank inventory changes only through conveyance, and an attempt on any other parcel is refused with `ERR_PROPERTY_NOT_IN_INVENTORY`. Recording an owner recomputes that applicant's delinquent-tax total, open-violation total and eligibility standing.

The registry also carries a graph. An `IntakeOfficer` records a shared-boundary edge between two parcels by supplying `property_id`, `adjacent_property_id` and the `shared_boundary_feet` of the boundary they share, which must be greater than zero. The edge is undirected: it is read from either endpoint, and the `recorded_by_user_id` of the officer who filed it is kept with it. An edge from a parcel to itself is refused with `ERR_SELF_ADJACENCY`, and a second edge over the same unordered pair of parcels — in either order — is refused with `ERR_ADJACENCY_DUPLICATE`. Recording an edge recomputes the `current_blight_score` of *both* parcels it touches, because each may now qualify for the neighbourhood-concentration bonus described in §3.6.

Prospective buyers are registered by a `DispositionOfficer` with a `legal_name` (1 to 160 characters), an `applicant_type` of `INDIVIDUAL`, `NONPROFIT` or `DEVELOPER`, a `contact_email` that must contain an at-sign, and — for nonprofits intending community reuse — a state `nonprofit_registration_no`. A fresh applicant starts with `reverter_count`, `good_standing_count`, `conveyed_property_count`, `delinquent_tax_total_cents`, `open_code_violation_total` and `recent_reverter_count` all zero, `last_reverter_at` null, and `eligibility_status` of `ELIGIBLE`.

### 3.2. Authorizing and Replenishing Funds

A `BoardClerk` authorizes money before it can be spent. The authorization carries a `name` of 1 to 120 characters, a `source_type` of `GRANT`, `TIF_RECAPTURE` or `GENERAL_FUND`, an `authorized_cents` ceiling of at least one cent, a `restriction` of `ANY`, `ACQUISITION_ONLY` or `DEMOLITION_ONLY`, and an `expires_on` instant after which the compliance sweep will retire it. The source opens in `ACTIVE` with `committed_cents`, `disbursed_cents`, `open_run_count` and `recaptured_cents` at zero, `available_cents` equal to `authorized_cents`, and `reserve_floor_cents` computed as 5 percent of the authorization rounded half up.

Authorizations grow only one way. A `CountyTreasurer` books a tax-increment recapture receipt by supplying `recapture_cents` and the `tax_year` it derives from; the amount is added both to `authorized_cents` and to the cumulative `recaptured_cents`, after which `available_cents`, `reserve_floor_cents` and `status` are all recomputed. Because the reserve floor is a percentage of a now-larger authorization, a recapture can leave a source above or below its floor; where it lifts the source back to at least its floor, the `CONSTRAINED → ACTIVE` transition fires and the parked packets described in §2.8 return to `DUE_DILIGENCE`.

The three funding states matter to different operators. An `ACTIVE` source accepts every category of commitment its `restriction` permits. A `CONSTRAINED` source still funds demolition, securing and mowing work — blight does not wait for a budget to recover — but it may not take a new acquisition commitment, and an attempt to board-approve a packet against it is refused with `ERR_FUNDING_CONSTRAINED`. An `EXPIRED` source funds nothing at all, and the orders it already funds can no longer be settled.

### 3.3. Acquisition: Due Diligence to Deed

An `IntakeOfficer` opens an acquisition packet against a registry parcel, naming the parcel with `property_id`, the budget with `funding_source_id`, and the `channel` — `TAX_FORECLOSURE`, `DONATION` or `NEGOTIATED_PURCHASE`. The consideration to be paid is `offer_price_cents` and the title search and recording cost is `title_search_fee_cents`; both are funded from the same source and neither may be negative. Each channel brings its own paperwork: a tax foreclosure requires the docket number as `foreclosure_case_no` and must not carry a donor, a donation requires the `donor_name` of record and must carry `offer_price_cents` of exactly zero, and a negotiated purchase carries neither of those two fields. A packet opens in `DUE_DILIGENCE` with `committed_cents` at zero and `initiated_by_user_id` set to the opening officer.

The board acts next. A `BoardClerk` board-approves a packet sitting in `DUE_DILIGENCE`, supplying the `resolution_no` the board voted under. Approval requires the funding source to be `ACTIVE`, its `restriction` to be `ANY` or `ACQUISITION_ONLY`, and its `available_cents` to be at least the sum of `offer_price_cents` and `title_search_fee_cents`; an insufficient balance is refused with `ERR_FUNDING_INSUFFICIENT`. On success the packet moves `DUE_DILIGENCE → BOARD_APPROVED`, records the resolution number, sets its own `committed_cents` to that same sum, and adds it to the source's `committed_cents`, after which `available_cents` is recomputed. If the new commitment drops `available_cents` below the source's reserve floor, the source moves `ACTIVE → CONSTRAINED` in the same request and every *other* packet on it still in `DUE_DILIGENCE` is parked in `ON_HOLD_FUNDING` with its `hold_reason` recorded. Both the packet's `version` and the funding source's `version` advance by one.

Closing is the four-eyes step. A different `IntakeOfficer` — one whose `X-User-ID` differs from `initiated_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES` — closes a `BOARD_APPROVED` packet by supplying the recorded `deed_reference`. Closing is refused with `ERR_PACKET_INVALID_STATE` from any other packet state. The parcel must still be `PROSPECT`, and the close drives the custody transition `PROSPECT → ACQUIRED` together with the whole intake stamping: the parcel copies the packet's channel into `acquisition_channel`, records `acquired_at` at the current instant, sets `acquisition_cost_cents` to the packet's offer price plus title search fee, and freezes the parcel's current `delinquent_tax_balance_cents` into `pre_acquisition_delinquency_cents` — the only delinquency the board will ever be able to discharge. The parcel's `intake_blight_score` is stamped once here with the provisional variant of the blight calculation and never recomputed thereafter, while `current_blight_score` is written with the live variant. The packet itself moves `BOARD_APPROVED → CLOSED`, records `closed_by_user_id`, and drops its `committed_cents` to zero as the commitment converts into money spent: the funding source's `disbursed_cents` grows by the offer price plus the title search fee, its `committed_cents` falls by exactly the same amount, and `available_cents` is recomputed — a swap that leaves the conserved ledger identity untouched. The parcel's `version` and the funding source's `version` each advance by one.

A packet can also be abandoned. An `IntakeOfficer` declines a packet in `DUE_DILIGENCE`, `ON_HOLD_FUNDING` or `BOARD_APPROVED`, supplying a `declined_reason`; all three routes — `DUE_DILIGENCE → DECLINED`, `ON_HOLD_FUNDING → DECLINED` and `BOARD_APPROVED → DECLINED` — are permitted, and `DECLINED` and `CLOSED` are the packet's two terminal states. Declining a packet that had been board-approved is the compensating action of approval: the packet's `committed_cents` returns to zero, the same amount is subtracted from the source's `committed_cents`, and `available_cents` is recomputed. If that release lifts `available_cents` back to at least `reserve_floor_cents`, the source moves `CONSTRAINED → ACTIVE` and every packet on it in `ON_HOLD_FUNDING` returns to `DUE_DILIGENCE`.

### 3.4. Clearing Title, and What Clear Title Unblocks

Tax foreclosures and donations arrive with clouded title, and nothing can be listed or conveyed until that is cured. An `IntakeOfficer` opens a title action on a parcel by naming the instrument as `action_type` — `QUIET_TITLE_SUIT`, `TAX_DEED_CONFIRMATION` or `LIEN_RELEASE`. Only one action may be open on a parcel at a time: while any action on the parcel is still in `FILED`, another filing is refused with `ERR_TITLE_ACTION_OPEN`. The new action opens in `FILED`, stamps `filed_at` at the current instant, and takes a `round_no` equal to the number of title actions already recorded on that parcel plus one, so the re-file that follows a defective adjudication is round 2. Filing drives the parcel's title dimension `CLOUDED → QUIET_TITLE_FILED` and bumps the parcel's `version`.

Adjudication closes the action with an `outcome` of either `CLEARED` or `DEFECT_REMAINS`, and the two branches are symmetric in shape but opposite in effect. A `CLEARED` outcome must carry no `defect_count`, or a `defect_count` of zero; the action moves `FILED → CLEARED`, records `adjudicated_at`, stores `defect_count` as zero, and drives the parcel `QUIET_TITLE_FILED → CLEAR`. A `DEFECT_REMAINS` outcome must carry a `defect_count` of at least one; the action moves `FILED → DEFECT_REMAINS`, records `adjudicated_at` and the reported defect count, and drives the parcel `QUIET_TITLE_FILED → CLOUDED`, reopening the filing cycle for another round. A mismatch between outcome and defect count is a malformed request. Adjudicating an action that already reached `CLEARED` or `DEFECT_REMAINS` is refused with `ERR_TITLE_ACTION_ALREADY_ADJUDICATED`. Both branches advance the parcel's `version` and the action's `version`.

Clearing title also releases work that a reverter had frozen. Every disposition application on the parcel that is parked in `SUSPENDED_TITLE` is restored, in the same request, to the exact status recorded in its `suspended_from_status` — `SUBMITTED`, `SCREENED` or `RECOMMENDED` — after which `suspended_from_status` is cleared to null and each restored application's `version` advances by one. Applications parked this way exit only through this route; they wait for the title to be cured rather than being resubmitted around it.

### 3.5. Holding the Inventory: Contractors, Windows and Work Orders

Work is performed by registered contractors. An `InventoryManager` registers one with a `name` of 1 to 120 characters, a `license_expires_on` instant, a `max_concurrent_crews` count of at least one, and a non-empty `specialties` list drawn from `SECURE`, `MOW` and `DEMOLITION`. The `debarred` flag may be supplied and defaults to false when omitted.

Scheduling an order names the `work_type` (`SECURE`, `MOW` or `DEMOLITION`), the `contractor_id` to perform it, the `funding_source_id` to pay for it, and a half-open work window running from an inclusive `window_start` to an exclusive `window_end` that must fall strictly after it — an inverted or empty window is refused with `ERR_WINDOW_INVALID`. A securing order additionally carries `openings_count`, the number of openings to be boarded, which must be at least one and is present for securing work only. The request also carries `expected_property_version` for the concurrency check of §2.9.

Only a parcel actually in the land bank's hands may be worked on: its `custody_status` must be `ACQUIRED`, `LISTED` or `REVERTED`, and an order against a registry-only `PROSPECT` parcel is refused with `ERR_PROPERTY_NOT_IN_INVENTORY`. The assigned contractor must not be `debarred` (`ERR_CONTRACTOR_DEBARRED`), its `specialties` must include the requested `work_type` (`ERR_CONTRACTOR_SPECIALTY_MISMATCH`), and the window may not extend past its licence: `window_end` at or before `license_expires_on` is accepted, anything later is refused with `ERR_CONTRACTOR_LICENSE_EXPIRED`. A demolition order additionally requires `structure_present` to be true on the parcel, or the request is refused with `ERR_DEMOLITION_REQUIRES_STRUCTURE`.

Three interval rules then apply. First, the parcel's own calendar is exclusive: the requested window may not intersect the window of any order on that parcel still in `SCHEDULED`, where two half-open windows intersect exactly when each starts strictly before the other ends; two windows that merely touch — one ending at the very instant the other begins — do not intersect and are both accepted. A conflict is `ERR_PROPERTY_WINDOW_CONFLICT`. Second, demolition needs breathing room: a demolition order must stand clear of every other `SCHEDULED` order on the same parcel by at least 72 hours, and the pair is rejected with `ERR_DEMOLITION_BUFFER_VIOLATION` when the other order starts strictly before the demolition window's end advanced by 72 hours *and* the other order ends strictly after the demolition window's start pulled back by 72 hours. The same buffer is applied in reverse when the new order is not a demolition and a `SCHEDULED` demolition order already exists on the parcel. Third, the contractor's crews are finite: count that contractor's `SCHEDULED` orders whose half-open windows intersect the requested one, and the count must be strictly less than `max_concurrent_crews` — a count equal to the crew ceiling is already a rejection, reported as `ERR_CONTRACTOR_CAPACITY_EXCEEDED`.

The cost of the work is computed by the authority, never quoted by the client, and written to `estimated_cost_cents`. The calculation is two-staged and the rounding order is pinned. For mowing, the single line item is the parcel's `lot_area_sqft` divided by 1,000 and rounded *up* to a whole thousand, multiplied by 1,850 cents — that is, $18.50 for every started thousand square feet — then rounded half up to whole cents. For securing, there are two line items: a flat base of 45,000 cents, and `openings_count` multiplied by 12,750 cents ($127.50 per boarded opening), rounded half up. For demolition, there are three line items: a base of 950,000 cents; a per-area charge of `lot_area_sqft` multiplied by 62 cents per square foot, rounded half up; and an asbestos surcharge that applies only when the parcel's `structure_condition_grade` is `D` or `F`, computed as 18 percent of the demolition base plus that rounded per-area charge, rounded half up, and zero for grades `A`, `B` and `C`. In every case the rounded line items are then summed into a subtotal, county overhead of 6.5 percent of that subtotal is computed and rounded half up as a second, separate step, and `estimated_cost_cents` is the subtotal plus that overhead. Only the named parcel's area and grade and the order's own work type and opening count participate; no other order or parcel influences the figure.

The estimate is committed before the work happens. The funding source's `restriction` must admit the category, its `available_cents` must be at least the estimate (`ERR_FUNDING_INSUFFICIENT` otherwise), and on success the estimate is added to `committed_cents`, `available_cents` is recomputed, and the source's `status` follows the reserve-floor rules of §2.8 — including parking `DUE_DILIGENCE` packets in `ON_HOLD_FUNDING` when the commitment pushes the source below its floor. The order opens in `SCHEDULED` with `actual_cost_cents`, `completed_at` and `cancelled_reason` all null, and `demolition_run_id` null unless the order was created by a demolition run. Both the parcel's `version` and the funding source's `version` advance.

Completion settles the money and changes the parcel. An `InventoryManager` completes an order still in `SCHEDULED` — anything else is `ERR_ORDER_NOT_SCHEDULED` — by supplying the invoiced `actual_cost_cents`, which may be zero but not negative. An order whose funding source has been swept to `EXPIRED` can no longer be completed and is refused with `ERR_FUNDING_SOURCE_EXPIRED`. On success the order moves `SCHEDULED → COMPLETED`, stores the actual cost and stamps `completed_at`. The funding source releases the estimate from `committed_cents` and adds the actual cost to `disbursed_cents` — the difference between estimate and invoice therefore returns to, or comes out of, `available_cents` — and the source's status is re-evaluated in both directions: a commitment-heavy position may still move `ACTIVE → CONSTRAINED` with the packet-parking cascade, while a favourable settlement may move `CONSTRAINED → ACTIVE` and release the parked packets back to `DUE_DILIGENCE`. The work itself lands on the parcel according to its type: securing sets `secured` to true, mowing stamps `last_mow_at` at the current instant, and demolition stamps `demolished_at` and sets `structure_present` to false. The parcel's `current_blight_score` is then recomputed with the live variant, and the order's, the parcel's and the funding source's `version` values each advance by one.

Cancellation is the compensating action of scheduling. Cancelling an order still in `SCHEDULED`, with a `cancelled_reason`, moves it `SCHEDULED → CANCELLED` and subtracts exactly `estimated_cost_cents` from the source's `committed_cents` with no disbursement whatsoever, after which `available_cents` is recomputed; if that release lifts the source back to at least its reserve floor, `CONSTRAINED → ACTIVE` fires and the parked packets return to `DUE_DILIGENCE`. When the cancelled order had been created by a demolition run, that run's `orders_created_count` is decremented.

### 3.6. Scoring Blight and Prioritizing Demolition

The authority ranks its demolition work by a blight priority score, evaluated in a fixed order over a single parcel and its adjacency edges. The structure term is zero when `structure_present` is false, and otherwise reads the condition grade: 0 points for grade `A`, 8 for `B`, 18 for `C`, 30 for `D` and 44 for `F`. The vacancy term is 0.25 points per month of `vacancy_months`, counting no more than 60 months — five years of vacancy is the most any parcel can claim. The complaint term is 1.5 points per nuisance complaint on file, capped at 12 points. The violation term is 3 points per open code-enforcement violation, capped at 15 points. The concentration bonus reads the adjacency graph symmetrically — an edge counts whichever endpoint the parcel occupies — and counts the distinct neighbouring parcels whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`, excluding neighbours that are merely `PROSPECT` or already `CONVEYED`; when at least two such neighbours are already in the land bank's hands, a flat 10-point bonus applies, and otherwise the bonus is zero. The holding term, described below, exists in only one of the two variants. The six terms are added at full precision, the sum is rounded half up to one decimal place, and the result is capped at 100 — the rounding and the cap are applied once, at the very end.

The score has two variants that differ in exactly one term. The **provisional intake** variant fixes the holding term at zero and is stamped once into `intake_blight_score` when an acquisition closes; because its inputs are frozen at that instant, it stays a historical snapshot forever. The **live** variant adds a holding term of 0.5 points for every *whole* 30-day month elapsed between the parcel's `acquired_at` and the current instant, capped at 12 points and treated as zero while `acquired_at` is null, and it re-reads complaint, violation and adjacency data each time. It is written to `current_blight_score` on acquisition close, on every code-enforcement posting, on the recording of an adjacency edge (for both parcels), on the completion of a maintenance order, when a demolition run selects candidates, when a run re-scores its selections at execution, and when a reverter returns a parcel to inventory. Because the live variant accrues holding points the provisional one never will, a parcel's `current_blight_score` drifts upward away from its `intake_blight_score` as it ages in inventory.

Planning a run is where scoring turns into money. An `InventoryManager` plans a run against a `funding_source_id` with a `budget_cents` ceiling of at least one cent, an optional `situs_ward_filter` between 1 and 9 that restricts candidates to that ward (a null filter means county-wide), and the `expected_funding_source_version` of §2.9. The budget may not exceed the source's `available_cents` at planning time — a budget exactly equal to the available balance is accepted, anything larger is refused with `ERR_RUN_BUDGET_EXCEEDS_AVAILABLE` — and the source's `restriction` must admit demolition spending.

The candidate set is explicit: a parcel qualifies when its `custody_status` is `ACQUIRED` or `LISTED`, its `title_status` is `CLEAR`, `structure_present` is true, its `current_blight_score` (refreshed with the live variant before ranking) is at least 40, it carries no maintenance order of type `DEMOLITION` in either `SCHEDULED` or `COMPLETED`, and — when a ward filter was supplied — its `situs_ward` equals that filter. Candidates are then ranked by `current_blight_score` from highest to lowest, ties broken by `lot_area_sqft` from largest to smallest, and remaining ties broken by `created_at` from oldest to newest; the record `id` is never a sort key.

Allocation resolves a circular dependency by pinning its evaluation order, because the administrative fee is a function of the committed subtotal while the subtotal must fit inside the budget net of that fee. First, `provisional_cap_cents` is the `budget_cents` divided by 1.075 and floored to whole cents — the budget with a 7.5 percent administrative loading carved out in advance — and it becomes the remaining capacity. The ranked candidates are then walked in order: once five parcels have been selected the run is full and every further candidate is skipped; otherwise the parcel's demolition estimate is computed exactly as in §3.5, and if that cost is no greater than the remaining capacity the parcel is selected and the cost is subtracted from the remaining capacity, while if the cost exceeds the remaining capacity the parcel is skipped and **the walk continues** — a parcel too expensive to fit does not stop cheaper, lower-ranked parcels from being taken. The selected parcels are recorded in allocation order in `selected_property_ids` and counted in `properties_selected_count`; those that ranked in but did not fit, together with those beyond the five-parcel ceiling, are recorded in `skipped_property_ids` and counted in `skipped_property_count`. `committed_subtotal_cents` is the sum of the selected parcels' estimates, `admin_fee_cents` is 7.5 percent of that subtotal rounded half up and evaluated only after the walk finishes, and `total_committed_cents` is the subtotal plus the fee — which the provisional cap guarantees can never exceed `budget_cents`.

Planning commits nothing. The run opens in `PLANNED` with `orders_created_count` at zero, `dropped_property_ids` empty and `executed_at` null, takes a `run_sequence` one greater than the number of runs already drawn on that source, and increments the source's `open_run_count` and `version`. When the candidate pool is empty the run is still created, in `PLANNED`, with `properties_selected_count` of zero and `total_committed_cents` of zero; an attempt to execute such a run is refused with `ERR_EMPTY_RUN` and the run stays `PLANNED`, available to be examined but never executed.

Execution re-validates the frozen snapshot without ever re-ranking it. Each selected parcel is re-scored with the live variant and re-checked against the candidate conditions; a parcel that has since acquired a `SCHEDULED` or `COMPLETED` demolition order, has left custody `ACQUIRED` or `LISTED`, or whose title is no longer `CLEAR`, is dropped. Executing a run that is not `PLANNED` is refused with `ERR_RUN_NOT_PLANNED`. If at least one selected parcel survives, the run moves `PLANNED → EXECUTED` and, walking the survivors in the stored allocation order, creates one maintenance order per parcel: `work_type` `DEMOLITION`, `contractor_id` left null so the work can be bid out afterwards, `funding_source_id` taken from the run, `demolition_run_id` pointing back at the run, a window opening at the current instant and closing 45 days later, `estimated_cost_cents` equal to the estimate stored during allocation, and status `SCHEDULED`. This is the head of a four-link cascade: each created order commits its estimate to the source's `committed_cents`; the run's `admin_fee_cents` is committed against the same source; `available_cents` is recomputed and, if it now sits below `reserve_floor_cents`, the source moves `ACTIVE → CONSTRAINED`; and that transition in turn parks every `DUE_DILIGENCE` packet on the source in `ON_HOLD_FUNDING`. The run records `orders_created_count`, `dropped_property_ids` and `executed_at`, the source's `open_run_count` falls by one, and the run's, the source's and every touched parcel's `version` advances.

When *no* selected parcel survives re-validation, the run moves `PLANNED → VOID` instead: `dropped_property_ids` becomes the whole of `selected_property_ids`, `orders_created_count` stays zero, not one cent is committed, the source's `open_run_count` still falls by one, and the run's and the source's `version` values still advance. `EXECUTED` and `VOID` are the run's two terminal states.

### 3.7. Listing, Community Reuse and What a Parcel Costs

A `DispositionOfficer` puts an inventory parcel on the market, moving it `ACQUIRED → LISTED` or, for a parcel the authority has taken back, `REVERTED → LISTED`, and stamping `listed_at` at the current instant. Both routes demand `title_status` of `CLEAR`, refusing anything else with `ERR_TITLE_NOT_CLEAR`; for a reverted parcel this means a fresh title action must have been filed and adjudicated `CLEARED` after the reverter deed re-clouded the title. A parcel with a demolition order still in `SCHEDULED` may not be listed at all and is refused with `ERR_PROPERTY_NOT_IN_INVENTORY` — the authority does not market a parcel it is about to knock down.

Community reuse planning runs alongside. A `DispositionOfficer` records a hearing on a parcel with the `hearing_at` instant it was held, the `comment_count` of public comments received, the `support_count` of those comments that were in support — which may never exceed the comment count — and a clerk's `summary` of 1 to 500 characters. The hearing's `support_ratio` is the support count divided by the comment count, rounded half up to four decimal places, and is exactly zero when no comments were received. Hearings are immutable observations: each carries an `id` and a `created_at` and nothing else from the common property set.

Pricing is computed from the parcel and the requested `program`, and can be read directly before anyone applies. The four programs price differently. A `SIDE_LOT` transfer starts at a base of 10,000 cents and adds 2 cents for every square foot of `lot_area_sqft` beyond the first 5,000 — the marginal area is zero when the lot is no larger than that free allowance — then caps the result at 25 percent of `assessed_value_cents` rounded half up, and finally raises it back to the 10,000-cent base if the cap pushed it below: the floor wins over the cap. A `HOMEOWNER_SALE` is 55 percent of `assessed_value_cents` rounded half up, but never less than a floor of 100,000 cents. A `DEVELOPER_RFP` is 90 percent of `assessed_value_cents` rounded half up, never less than a floor of 500,000 cents. A `COMMUNITY_USE` transfer is a nominal 100 cents, which is also its floor. After the programme tier is settled, a condition discount applies to every programme except `COMMUNITY_USE`: when the parcel has a structure standing and its `structure_condition_grade` is `D` or `F`, 15 percent of the quoted figure, rounded half up, is subtracted — but the result is never allowed below the programme's own floor. The computed read answers with the `program` requested, the resulting `quoted_price_cents`, a `tier_applied` naming the programme tier that produced it, the `marginal_area_sqft` charged beyond the side-lot allowance (zero for the other three programmes), the `assessed_cap_cents` figure derived from the assessed value (the 25 percent cap for a side lot, the 55 percent figure for a homeowner sale, the 90 percent figure for a developer request for proposals, and zero for community use), and a `discount_applied` flag recording whether the condition discount was subtracted.

An application is drafted against a listed parcel by a `DispositionOfficer` or by the buyer itself, naming the `property_id`, the `applicant_id`, the `program`, a `proposed_use` narrative of 1 to 500 characters, and the buyer's `offer_price_cents`. The draft opens in `DRAFT` with `revision_round` and `screening_count` at zero, `submitted_at`, `suspended_from_status`, `recommended_by_user_id`, `recommendation_memo`, `decided_by_user_id`, `board_decision_at` and `denial_reason` all null, and `quoted_price_cents` populated from the price calculation above.

Submission is where the statutory gates bite, and the `Applicant` itself performs it, driving `DRAFT → SUBMITTED`. The parcel must still be `LISTED`, or the submission is refused with `ERR_PROPERTY_NOT_LISTED`. The buyer must owe the county nothing: any delinquent-tax total strictly greater than zero across the parcels it owns of record bars the sale with `ERR_APPLICANT_TAX_DELINQUENT`, and two or more open code-enforcement violations across those same parcels bars it with `ERR_APPLICANT_CODE_VIOLATOR`. Programme and applicant class must match: `SIDE_LOT` and `HOMEOWNER_SALE` are open to an `INDIVIDUAL`, `DEVELOPER_RFP` to a `DEVELOPER` and `COMMUNITY_USE` to a `NONPROFIT`, with any other pairing refused as `ERR_APPLICANT_TYPE_NOT_ELIGIBLE`. A community-use applicant must additionally carry a `nonprofit_registration_no` (`ERR_NONPROFIT_REGISTRATION_REQUIRED`). A side-lot request demands a vacant target parcel — `structure_present` false, else `ERR_SIDE_LOT_REQUIRES_VACANT` — and demands that the applicant already own the parcel next door: there must be an adjacency edge with `shared_boundary_feet` of at least 20 linking the target parcel to some parcel the applicant owns of record, in either direction of the edge, or the request is refused with `ERR_NOT_ADJACENT_OWNER`. Community-use requests are also tested against the community's own verdict, using the governing hearing on that parcel — the one with the greatest `hearing_at`, ties broken by the greater `created_at`. That hearing must exist and have been held no more than 180 days before the current instant, or the submission fails with `ERR_HEARING_STALE`; the quorum and support test runs strictly after the freshness test, so a hearing with no comments is turned away by quorum rather than by a division. Quorum and support are one rule: the governing hearing needs at least 5 comments and a `support_ratio` of at least 0.60, failing which the submission is refused with `ERR_HEARING_SUPPORT_INSUFFICIENT`. A homeowner sale is barred outright when the applicant already holds two or more parcels of record in custody `CONVEYED` (`ERR_HOMEOWNER_LIMIT_EXCEEDED`). Last, the money: the buyer's `offer_price_cents` must be at least the computed quote for that parcel and programme, or the submission is refused with `ERR_OFFER_BELOW_QUOTE`. On success the application records the quote into `quoted_price_cents`, stamps `submitted_at` at the current instant and advances its `version`.

### 3.8. Screening, Recommendation and the Board's Award

A `DispositionOfficer` screens an application that is in `SUBMITTED`; any other status is refused with `ERR_APPLICATION_INVALID_STATE`. Screening writes an immutable eligibility screening record carrying only an `id` and a `created_at` besides its own fields: the `application_id` screened, a `sequence_no` one greater than the application's current `screening_count`, the `screened_by_user_id` of the officer, `screened_at` at the current instant, and the evidence the decision rested on.

That evidence is a cross-entity roll-up over the buyer. The parcels considered are those whose `owner_of_record_applicant_id` is the applicant *and* whose `custody_status` is `PROSPECT` or `CONVEYED`; a parcel that has been reverted is back in the land bank's hands and drops out of the roll-up entirely. `delinquent_tax_total_cents` is the sum of `delinquent_tax_balance_cents` over those parcels, `open_code_violation_total` is the sum of their `open_code_violation_count`, and `conveyed_property_count` counts those of them in `CONVEYED`. `recent_reverter_count` counts the development agreements attributable to this applicant that reached `REVERTED` with a `reverted_at` no earlier than 1,825 days — five years — before the current instant. Each screening keeps its own snapshot of the three roll-ups, so a later screening can be compared against an earlier one.

The `disqualifiers` array is appended to in exactly this order, and the order is part of the contract: `DELINQUENT_TAXES` when the delinquent-tax total is strictly greater than zero; `CODE_VIOLATIONS` when the open-violation total is at least 2; `RECENT_REVERTER` when at least one reverter falls inside the five-year lookback; `NONPROFIT_REGISTRATION_MISSING` when the programme is `COMMUNITY_USE` and the applicant carries no `nonprofit_registration_no`; `NOT_ADJACENT_OWNER` when the programme is `SIDE_LOT` and no adjacency edge with `shared_boundary_feet` of at least 20 links the requested parcel to a parcel the applicant owns of record; and `INSUFFICIENT_OFFER` when the application's `offer_price_cents` is below the computed quote for that parcel and programme. The `eligibility_score` is 100 reduced by 25 points for each disqualifier recorded, never falling below zero, and the `outcome` is `PASS` when the array is empty and `FAIL` otherwise.

The two branches diverge sharply. A `PASS` moves the application `SUBMITTED → SCREENED`. A `FAIL` moves it `SUBMITTED → DENIED` — a terminal status — and writes `denial_reason` as the literal `SCREENING_FAIL:` followed immediately by the first disqualifier code in the array. Either way the application's `screening_count` grows by one and its `version` advances. The same roll-up drives the applicant record's own standing: `eligibility_status` is `BARRED` whenever the delinquent-tax total is strictly greater than zero, or the open-violation total is at least 2, or at least one reverter falls in the lookback window, and `ELIGIBLE` otherwise. It is recomputed on every tax roll posting, code-enforcement posting, owner-of-record change, conveyance and reverter.

A screened or freshly submitted application can be sent back for more information. A `DispositionOfficer` returns it with the text of what is wanted in `information_requested`, moving it `SUBMITTED → INFO_REQUESTED` or `SCREENED → INFO_REQUESTED` and recording in `suspended_from_status` the status the application held when it was interrupted. The buyer then resubmits, optionally revising `offer_price_cents` and `proposed_use`, driving `INFO_REQUESTED → SUBMITTED`; this closes the revision cycle `SUBMITTED → INFO_REQUESTED → SUBMITTED`, which may be travelled at most twice. A resubmission is accepted only while `revision_round` is strictly below 2, and the third attempt is refused with `ERR_REVISION_LIMIT_EXCEEDED`. A resubmission re-runs the entire submission gate ladder of §3.7 against the revised offer and the *current* state of the parcel and the buyer — nothing is grandfathered — then increments `revision_round`, refreshes `submitted_at`, recomputes `quoted_price_cents`, clears `suspended_from_status` to null and advances the `version`.

Recommendation is the officer's last act. A `DispositionOfficer` recommends an application in `SCREENED`, supplying a `recommendation_memo`, and drives `SCREENED → RECOMMENDED`. Four conditions guard it. The governing screening — the one with the greatest `sequence_no` — must have `outcome` of `PASS`, or the recommendation is refused with `ERR_APPLICATION_INVALID_STATE`. The acting user must not be that screening's `screened_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`. The parcel's `title_status` must still be `CLEAR` (`ERR_TITLE_NOT_CLEAR`) and its `custody_status` must still be `LISTED` (`ERR_PROPERTY_NOT_LISTED`). On success the application records `recommended_by_user_id` and the memo, and advances its `version`.

The board then decides. A `BoardClerk` records a `decision` of `APPROVE` or `DENY` on an application in `RECOMMENDED`, together with the `resolution_no` the board voted under and, on a denial, a `denial_reason`. `APPROVE` drives `RECOMMENDED → BOARD_APPROVED` and additionally requires the parcel to still be `LISTED`, refusing anything else with `ERR_PROPERTY_NOT_LISTED`; `DENY` drives `RECOMMENDED → BOARD_DENIED`, a terminal status, and records the reason. Both branches stamp `decided_by_user_id` and `board_decision_at` and advance the `version`.

### 3.9. Conveyance, Reverter Enforcement and the Periodic Sweep

A `BoardClerk` papers a board-approved award into a development agreement, naming the `application_id` and setting the terms: the `performance_deadline` by which every milestone must be reported, the `milestone_count` of milestones owed (at least one), the `reverter_clause_active` flag that decides whether a missed cure period costs the buyer the deed, the `abatement_years` of tax abatement the board granted, the `discharge_mode` of `STATUTORY` or `NEGOTIATED`, and the buyer's `projected_improved_value_cents` after improvement. At most one agreement may exist per application, and this uniqueness test is evaluated before the application-state and parcel-custody tests, so a replayed execution reports `ERR_AGREEMENT_ALREADY_EXISTS` rather than a misleading state error. The application must be in `BOARD_APPROVED` (`ERR_APPLICATION_INVALID_STATE`) and the parcel must be `LISTED` (`ERR_PROPERTY_NOT_LISTED`) — a parcel already `CONVEYED`, or still only `ACQUIRED`, is not on the market — which by the listing rule also means its `title_status` is `CLEAR`. The `performance_deadline` must fall strictly after the current instant (`ERR_DEADLINE_IN_PAST`), and `abatement_years` must lie between 0 and 10 inclusive — 10 is accepted, 11 is refused with `ERR_ABATEMENT_YEARS_EXCEED_CAP`.

Execution is the conveyance, and it also exercises the board's tax authority. The agreement opens in `EXECUTED`, stamps `executed_at`, sets `milestones_completed` to zero, leaves `cure_deadline`, `complied_at` and `reverted_at` null, copies the parcel reference into `property_id` and copies the application's `offer_price_cents` into `sale_price_cents`. The relief then follows the chosen mode, and only the frozen `pre_acquisition_delinquency_cents` is ever dischargeable — delinquency posted after the authority took the parcel is not. Under `STATUTORY`, `discharged_tax_cents` is the whole of that frozen pre-acquisition delinquency and the abatement is computed against the buyer's `projected_improved_value_cents`. Under `NEGOTIATED`, `discharged_tax_cents` is the lesser of that frozen delinquency and 40 percent of `sale_price_cents` rounded half up, and the abatement is computed against the parcel's pre-improvement `assessed_value_cents` instead. In both modes `abatement_annual_cents` is the county millage of 0.0142 applied to the chosen base and rounded half up, then capped at 250,000 cents a year, and `abatement_total_cents` is that annual figure multiplied by `abatement_years`. The parcel's `delinquent_tax_balance_cents` is reduced by `discharged_tax_cents` and floored at zero. Because the two modes read different bases and apply a different cap, identical inputs produce a different discharge and a different annual abatement under each — a statutory discharge exceeds a negotiated one whenever 40 percent of the sale price falls short of the frozen delinquency, and a statutory abatement exceeds a negotiated one whenever the projected improved value exceeds the assessed value.

The conveyance itself moves the parcel `LISTED → CONVEYED`, sets its `owner_of_record_applicant_id` to the buyer, and moves the application `BOARD_APPROVED → AWARDED`, the last of its terminal statuses. The parcel's `lot_area_sqft` leaves the conserved inventory area described in §2.11 for the conveyed area. The buyer's `conveyed_property_count`, `delinquent_tax_total_cents` and `open_code_violation_total` are recomputed and its `eligibility_status` re-evaluated — a conveyance can itself bar a buyer from the next parcel, since delinquency on a parcel it now owns of record counts against it. The parcel's `version` and the application's `version` each advance by one.

Performance is reported by the buyer. Each report supplies a `completed_count` of milestones and an `evidence_reference` for the file, and adds that count to `milestones_completed`, which may never exceed `milestone_count` — an overrun is refused with `ERR_MILESTONE_OVERFLOW`. Reporting against an agreement already in `COMPLIED` or `REVERTED` is refused with `ERR_AGREEMENT_INVALID_STATE`. When a report brings `milestones_completed` exactly up to `milestone_count`, the agreement complies — `EXECUTED → COMPLIED` or `CURE_PENDING → COMPLIED` — provided the report lands inside the applicable deadline: from `EXECUTED` the reporting instant must be no later than the `performance_deadline`, and from `CURE_PENDING` no later than the `cure_deadline`. A final report that lands past the applicable deadline still adds its `completed_count` to `milestones_completed`, but confers no compliance: the agreement stays where it is and remains exposed to the sweep. Compliance from either state stamps `complied_at`, increases the buyer's `good_standing_count` by one, releases the reverter by clearing `reverter_clause_active`, and advances both the agreement's and the applicant's `version`; the parcel stays `CONVEYED` and can no longer be taken back by a sweep. `COMPLIED` and `REVERTED` are the agreement's terminal states.

The compliance sweep is the authority's clock-driven enforcement pass, run by an `InventoryManager`, and it works in three ordered steps at the current logical instant. **Step one** expires money: every funding source whose `expires_on` falls strictly before the current instant moves `ACTIVE → EXPIRED` or `CONSTRAINED → EXPIRED`, and each such move advances that source's `version`. **Step two** opens cure periods: every agreement in `EXECUTED` whose `performance_deadline` has passed while `milestones_completed` remains below `milestone_count` moves `EXECUTED → CURE_PENDING` and has its `cure_deadline` stamped 90 days after its `performance_deadline`. **Step three** enforces the reverter: every agreement in `CURE_PENDING` whose `cure_deadline` has passed while milestones remain outstanding, and whose `reverter_clause_active` is true, moves `CURE_PENDING → REVERTED` and stamps `reverted_at`; where `reverter_clause_active` is false the agreement is left in `CURE_PENDING` and the sweep merely counts it as waived.

Each reverter fires a chain of four linked consequences. The agreement's `reverted_at` is stamped; the parcel moves `CONVEYED → REVERTED`, has its `owner_of_record_applicant_id` cleared to null, has its `delinquent_tax_balance_cents` restored by the `discharged_tax_cents` the agreement had forgiven, and has its `current_blight_score` recomputed with the live variant, while its `lot_area_sqft` returns to the conserved inventory area; the reverter deed re-clouds the title, driving `CLEAR → CLOUDED`; and that re-clouding suspends the parcel's live disposition pipeline — every application on that parcel in `SUBMITTED`, `SCREENED` or `RECOMMENDED` records its current status in `suspended_from_status` and moves to `SUSPENDED_TITLE` — the three routes `SUBMITTED → SUSPENDED_TITLE`, `SCREENED → SUSPENDED_TITLE` and `RECOMMENDED → SUSPENDED_TITLE` — to be restored only by a fresh title clearing, which drives `SUSPENDED_TITLE → SUBMITTED`, `SUSPENDED_TITLE → SCREENED` or `SUSPENDED_TITLE → RECOMMENDED` as described in §3.4. The former buyer pays for it too: its `reverter_count` grows by one, `last_reverter_at` is stamped at the current instant, `recent_reverter_count` is recomputed and its `eligibility_status` becomes `BARRED`, which keeps it out of the market for the whole five-year lookback. The parcel's, the agreement's and the applicant's `version` values each advance by one.

The sweep answers with a tally of what it did: the `swept_at` instant it ran at, the `funding_expired_count` of sources retired, the `cure_pending_count` of agreements moved into cure, the `reverted_count` of deeds taken back, the `waived_count` of defaults left standing because the reverter clause was inactive, and the `restored_inventory_sqft` of land returned to inventory.

Finally, any staff role can read the authority-wide position, optionally narrowed to one `situs_ward`: `inventory_property_count`, `inventory_area_sqft` and `conveyed_area_sqft` from the conserved-area rules of §2.11, the `cure_pending_count` of agreements currently in their cure window, and the ledger identity totals across every funding source — `total_authorized_cents`, `total_committed_cents`, `total_disbursed_cents` and `total_available_cents`, which must always satisfy the identity of §2.8.

## 4. Endpoint Definitions

Operations that mint a new record — registering a parcel, a contractor, a funding source, an applicant, an acquisition packet, a title action, an adjacency edge, a reuse hearing, a maintenance order, a demolition run, a disposition application, an eligibility screening or a development agreement — answer with `201 Created`. Operations that advance or amend an existing record, including every state transition, every county data posting, the compliance sweep and every read, answer with `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/land-bank/properties` | Register a parcel in the land bank prospect registry | IntakeOfficer |
| GET | `/land-bank/properties/{id}` | Read one parcel with its custody, title, blight and maintenance fields | All six roles |
| GET | `/land-bank/properties` | List parcels, filterable by custody, title, ward and owner of record | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |
| POST | `/land-bank/properties/{id}/code-violation-report` | Post the code-enforcement snapshot for a parcel | IntakeOfficer |
| POST | `/land-bank/properties/{id}/tax-roll-posting` | Post the county tax roll delinquency balance for a parcel | CountyTreasurer |
| POST | `/land-bank/properties/{id}/owner-of-record` | Record the private owner of record for a registry parcel | IntakeOfficer |
| POST | `/land-bank/properties/{id}/list` | List an inventory parcel for disposition | DispositionOfficer |
| GET | `/land-bank/properties/{id}/price-quote` | Computed read: the disposition price quote under the requested program | DispositionOfficer, Applicant |
| POST | `/land-bank/properties/{id}/title-actions` | Open a title-clearing action on a parcel | IntakeOfficer |
| GET | `/land-bank/properties/{id}/title-actions` | List every title action recorded against a parcel, oldest first | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer |
| POST | `/land-bank/title-actions/{id}/adjudicate` | Adjudicate an open title action | IntakeOfficer |
| POST | `/land-bank/properties/{id}/reuse-hearings` | Record a community reuse-planning hearing for a parcel | DispositionOfficer |
| GET | `/land-bank/properties/{id}/reuse-hearings` | List the reuse hearings held for a parcel, newest hearing first | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, Applicant |
| POST | `/land-bank/parcel-adjacencies` | Record a shared-boundary edge between two parcels | IntakeOfficer |
| GET | `/land-bank/properties/{id}/adjacencies` | List the adjacency edges touching a parcel, in either direction | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, Applicant |
| POST | `/land-bank/funding-sources` | Authorize a funding source with a spend restriction and expiry | BoardClerk |
| GET | `/land-bank/funding-sources/{id}` | Read one funding source with its full commitment ledger position | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |
| GET | `/land-bank/funding-sources/{id}/demolition-runs` | List the demolition runs drawn against a funding source | BoardClerk, InventoryManager, CountyTreasurer |
| POST | `/land-bank/funding-sources/{id}/tif-recapture` | Post a tax-increment recapture receipt onto a funding source | CountyTreasurer |
| POST | `/land-bank/acquisition-packets` | Open an acquisition packet against a registry parcel | IntakeOfficer |
| GET | `/land-bank/acquisition-packets/{id}` | Read one acquisition packet | IntakeOfficer, BoardClerk, CountyTreasurer |
| GET | `/land-bank/acquisition-packets` | List acquisition packets, filterable by parcel, funding source and status | IntakeOfficer, BoardClerk, CountyTreasurer |
| POST | `/land-bank/acquisition-packets/{id}/board-approval` | Board-approve a packet and commit its cost against the funding source | BoardClerk |
| POST | `/land-bank/acquisition-packets/{id}/close` | Close a board-approved acquisition and move the parcel into inventory | IntakeOfficer |
| POST | `/land-bank/acquisition-packets/{id}/decline` | Decline a packet and release any commitment | IntakeOfficer |
| POST | `/land-bank/contractors` | Register a maintenance/demolition contractor | InventoryManager |
| POST | `/land-bank/properties/{id}/maintenance-orders` | Schedule a securing, mowing or demolition order on an inventory parcel | InventoryManager |
| GET | `/land-bank/maintenance-orders/{id}` | Read one maintenance order | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |
| GET | `/land-bank/maintenance-orders` | List maintenance orders with the documented filters | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |
| POST | `/land-bank/maintenance-orders/{id}/complete` | Complete a scheduled order with its actual cost | InventoryManager |
| POST | `/land-bank/maintenance-orders/{id}/cancel` | Cancel a scheduled order and release its estimate | InventoryManager |
| POST | `/land-bank/demolition-runs` | Plan a demolition prioritization run against a funding source budget | InventoryManager |
| POST | `/land-bank/demolition-runs/{id}/execute` | Execute a planned run, creating demolition orders for surviving parcels | InventoryManager |
| POST | `/land-bank/applicants` | Register a prospective buyer | DispositionOfficer |
| GET | `/land-bank/applicants/{id}` | Read one applicant with the aggregates that drive screening | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer, Applicant |
| POST | `/land-bank/disposition-applications` | Draft a disposition application for a listed parcel | DispositionOfficer, Applicant |
| GET | `/land-bank/disposition-applications/{id}` | Read one disposition application | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer, Applicant |
| GET | `/land-bank/disposition-applications` | List disposition applications with the documented filters | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer |
| POST | `/land-bank/disposition-applications/{id}/submit` | Submit a draft application through the full validation ladder | Applicant |
| POST | `/land-bank/disposition-applications/{id}/screen` | Run a buyer eligibility screening on a submitted application | DispositionOfficer |
| GET | `/land-bank/disposition-applications/{id}/screenings` | List the eligibility screenings of an application, oldest first | IntakeOfficer, BoardClerk, DispositionOfficer, Applicant |
| POST | `/land-bank/disposition-applications/{id}/request-info` | Return an application to the applicant for more information | DispositionOfficer |
| POST | `/land-bank/disposition-applications/{id}/resubmit` | Resubmit an application with a revised offer or use | Applicant |
| POST | `/land-bank/disposition-applications/{id}/recommend` | Recommend a screened application to the board | DispositionOfficer |
| POST | `/land-bank/disposition-applications/{id}/board-decision` | Record the board's decision on a recommended application | BoardClerk |
| POST | `/land-bank/development-agreements` | Execute the development agreement and convey the parcel | BoardClerk |
| GET | `/land-bank/development-agreements/{id}` | Read one development agreement with its deadlines and abatement figures | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer, Applicant |
| GET | `/land-bank/development-agreements` | List development agreements with the documented filters | IntakeOfficer, BoardClerk, DispositionOfficer, CountyTreasurer |
| POST | `/land-bank/development-agreements/{id}/milestone-completions` | Report completed development milestones | Applicant |
| POST | `/land-bank/compliance-sweeps` | Run the periodic compliance sweep at the current logical clock | InventoryManager |
| GET | `/land-bank/inventory-summary` | Computed read: authority-wide conserved area and ledger positions | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical UTC clock | IntakeOfficer, BoardClerk, DispositionOfficer, InventoryManager, CountyTreasurer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_NOT_APPLICATION_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_FUNDING_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_PACKET_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PROPERTY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FUNDING_SOURCE_VERSION` | 412 Precondition Failed |
| `ERR_PACKET_INVALID_STATE` | 409 Conflict |
| `ERR_TITLE_ACTION_ALREADY_ADJUDICATED` | 409 Conflict |
| `ERR_TITLE_ACTION_OPEN` | 409 Conflict |
| `ERR_TITLE_NOT_CLEAR` | 409 Conflict |
| `ERR_PROPERTY_NOT_IN_INVENTORY` | 409 Conflict |
| `ERR_PROPERTY_NOT_LISTED` | 409 Conflict |
| `ERR_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_FUNDING_SOURCE_EXPIRED` | 409 Conflict |
| `ERR_RUN_NOT_PLANNED` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICANT_TAX_DELINQUENT` | 422 Unprocessable Entity |
| `ERR_APPLICANT_CODE_VIOLATOR` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_DEBARRED` | 422 Unprocessable Entity |
| `ERR_APPLICANT_TYPE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_NONPROFIT_REGISTRATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SIDE_LOT_REQUIRES_VACANT` | 422 Unprocessable Entity |
| `ERR_NOT_ADJACENT_OWNER` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_SPECIALTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_LICENSE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_HEARING_STALE` | 422 Unprocessable Entity |
| `ERR_HEARING_SUPPORT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DEADLINE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_PROPERTY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DEMOLITION_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_CONTRACTOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SELF_ADJACENCY` | 422 Unprocessable Entity |
| `ERR_ADJACENCY_DUPLICATE` | 409 Conflict |
| `ERR_PARCEL_ID_DUPLICATE` | 409 Conflict |
| `ERR_DEMOLITION_REQUIRES_STRUCTURE` | 422 Unprocessable Entity |
| `ERR_OFFER_BELOW_QUOTE` | 422 Unprocessable Entity |
| `ERR_REVISION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_HOMEOWNER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MILESTONE_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ABATEMENT_YEARS_EXCEED_CAP` | 422 Unprocessable Entity |
| `ERR_EMPTY_RUN` | 422 Unprocessable Entity |
| `ERR_FUNDING_RESTRICTION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_FUNDING_CONSTRAINED` | 422 Unprocessable Entity |
| `ERR_FUNDING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_RUN_BUDGET_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
