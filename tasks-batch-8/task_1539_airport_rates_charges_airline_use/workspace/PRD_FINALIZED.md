# Airport Rates & Charges API — Product Requirements Document

## 1. Introduction

An airport's finance department lives and dies by its airline use agreement: the document that decides how the airfield and terminal cost centers are allocated, how landing fees and terminal rents are set, and how the books are trued up when the fiscal year closes. Getting this wrong is expensive in both directions — overcharge the carriers and the airport faces disputes and sour negotiations; undercharge and the residual shortfall lands on the airport's own ledger. This API is the operational backbone for that agreement. It administers the full annual cycle of airport rates and charges: standing up a fiscal year with its cost pools and traffic forecast, deriving and consulting on the rate schedule, recording landed-weight activity and billing against the adopted rates, running capital projects through majority-in-interest approval, collecting Passenger Facility Charge remittances, and finally computing, disputing, and settling the year-end true-up.

Two design commitments shape everything that follows. First, the airport supports three rate-setting philosophies — residual, compensatory, and a hybrid of the two — and the chosen philosophy changes how the prior year's surplus or deficit flows into this year's requirement, so the methodology is a first-class input rather than an implementation detail. Second, carriers are not all treated alike: signatory airlines that countersign the agreement earn a materially lower landing fee than non-signatory operators, and that differential, the consultation record, and the voting weight of each carrier all have to be defensible to auditors. Every rate derivation, every billed charge, and every settlement line is therefore computed from explicit, deterministic rules, and all time-dependent behavior — consultation windows, countersign deadlines, dispute windows, payment due dates — is driven by a logical clock rather than the wall clock, so that every outcome is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles: `AirportFinance`, `AirportDirector`, `SignatoryAirline`, and `AirportAuditor`. A request whose role header is missing or names an unrecognized role is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `AirportFinance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`. The same holds when `X-User-Role` is `AirportDirector`: `X-User-ID` is an opaque identifier for the director's office, never matched against stored entities. When `X-User-Role` is `SignatoryAirline`, `X-User-ID` is the `id` of the acting `Airline`; ownership checks on any resource that references an `Airline` compare the resource's `airline_id` field to `X-User-ID`. Finally, when `X-User-Role` is `AirportAuditor`, `X-User-ID` is again an opaque identifier for the audit function and is never compared to an entity `id`. Reading is broad — every role may call every read endpoint — while writing is tightly partitioned per the endpoint table in §4. `AirportAuditor` performs no writes at all.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Certain list endpoints additionally accept filters expressed as query parameters: the fiscal-year list filters by `status` and `methodology`; the airline list filters by `carrier_class` and `pfc_approved`; a fiscal year's activity list filters by `airline_id` and `signature_status_at_activity`; a capital project's vote list filters by `ballot`; a settlement's line list filters by `airline_id` and `payment_status`; and a fiscal year's PFC application list filters by `airline_id` and `status`.

### 2.4. The Airport's Logical Clock

Every deadline, window, and expiry in this system is evaluated against a server-held logical clock, never against the wall clock. Before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. A test-driving capability available to `AirportFinance` and `AirportDirector` sets the clock: the request carries a `to_iso8601` timestamp and the response reports the resulting `current_utc`. Once set, the clock stays where it was put until the next explicit adjustment.

The logical clock governs five time-sensitive operations: adopting a rate schedule (which requires a minimum consultation period to have elapsed), countersigning an agreement (which must happen before the countersign deadline), disputing a settlement (which must happen inside the dispute window), recording flight activity (whose activity date must fall inside the fiscal year's own window), and finalizing a settlement. A temporal precondition that fails is reported under the temporal validation family: `ERR_TEMPORAL_VIOLATION` is the general code, while a late countersignature and an out-of-window dispute surface under their own specialized codes introduced in §3.

### 2.5. Common Resource Properties

All primary resources — fiscal years, airlines, agreements, rate settings, capital projects, settlements, settlement lines, and PFC applications — share a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), set when the resource is first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource, including modifications caused by automatic cascades.

Three resources are immutable, event-style records and deliberately carry less. A `ConsultationComment`, an `ActivityRecord`, and an `MIIVote` each receive only `id` and `created_at` among the common properties; both `updated_at` and `version` are absent on these three types, because their content never changes after creation.

### 2.6. Money, Precision, and Rounding Conventions

Every monetary quantity in the system — cost pools, revenue offsets, rates, billed charges, settlement shares, true-up amounts, and PFC amounts — is represented as an integer number of cents. Monetary values in API request and response bodies are numbers, never strings.

Wherever a division or proportional allocation produces a fractional cent, the result is rounded half up to the nearest whole cent. Exactly one derivation deviates: the non-signatory landing fee is obtained by scaling the signatory fee and then rounding up to the next whole cent whenever the scaled value is not already an exact integer — a markup is never partially surrendered. The one non-monetary computed figure, the signatory-versus-non-signatory rate differential, is a percentage rounded half up to two decimal places.

### 2.7. Cost Centers, Rate Methodologies, and the Signatory Differential

The airport divides its finances into two cost centers. The **airfield** cost center absorbs runways, taxiways, and their associated operating and capital-amortization costs; the **terminal** cost center absorbs the building side. A capital project is always tagged with exactly one `cost_center`, either `AIRFIELD` or `TERMINAL`, indicating which pool would absorb its cost. Each fiscal year carries its airfield pool in `airfield_opex_cents` and its terminal pool in `terminal_opex_cents`, and each pool is offset by the non-airline revenue credited against it — `nonairline_airfield_revenue_cents` for items such as concessions and fuel flowage, `nonairline_terminal_revenue_cents` for items such as retail and the parking share.

Each fiscal year selects a `methodology` that determines how the prior year's settlement outcome feeds the current year's rates. Under `RESIDUAL`, the signatory carriers collectively underwrite the airport's remaining costs: the prior-year surplus or deficit carried in `prior_year_surplus_cents` flows into the airfield requirement in full. Under `COMPENSATORY`, the airport absorbs its own year-over-year risk and the carry-forward is excluded entirely — for a compensatory year `prior_year_surplus_cents` defaults to zero and plays no part in any derivation. Under `HYBRID`, exactly half of the carry-forward flows into the requirement. An operation that is only meaningful under a different methodology is rejected with `ERR_METHODOLOGY_MISMATCH`; creating a compensatory year carrying a non-zero `prior_year_surplus_cents` is not such an operation — §3.1's creation contract accepts the carry-forward under every methodology and stores it on the year, and the compensatory exclusion is applied purely at derivation time.

Signatory status is the commercial fulcrum of the agreement. Carriers that countersign earn the signatory landing fee; carriers that do not are charged at a non-signatory fee built from the signatory fee with a 125 percent markup. The same dual-track philosophy runs through settlement: non-signatory carriers paid their premium at charge time and therefore do not participate in the residual true-up.

### 2.8. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so the reported failure is deterministic. Authentication comes first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization follows: a recognized role that is not permitted for the endpoint yields `ERR_FORBIDDEN`. Path-parameter existence comes next, validated left to right, with the first unresolvable identifier producing `ERR_NOT_FOUND`. References inside the request body are then resolved — an `airline_id`, `fiscal_year_id`, `capital_project_id`, or `annual_settlement_id` that names nothing yields `ERR_FK_NOT_FOUND`. Field shape follows: a missing required field, a wrong-typed value, or an enum value outside its declared set yields `ERR_INVALID_REQUEST`. Only after the request is well-formed does the server ask whether the target resource's current state admits the requested transition (`ERR_INVALID_STATE`), whether an optimistic-concurrency-guarded write carries the parent resource's current `version` (`ERR_STALE_VERSION`), and whether the logical clock satisfies the applicable time window (`ERR_TEMPORAL_VIOLATION`). The year-level and carrier-level safety guards come after those: a write scoped beneath a `CLOSED` fiscal year yields `ERR_FISCAL_YEAR_CLOSED`, and a suspended carrier's attempt to file activity or PFC traffic yields `ERR_AIRLINE_SUSPENDED`. Endpoint-specific business rules rank last of all: vote eligibility (`ERR_NOT_SIGNATORY`), the one-ballot-per-carrier rule (`ERR_DUPLICATE_VOTE`), a project no longer accepting votes (`ERR_PROJECT_ALREADY_DECIDED`), rate derivability (`ERR_RATE_NOT_DERIVABLE`), the presence of activity at settlement compute (`ERR_NO_ACTIVITY`), unsettled lines at finalization (`ERR_UNSETTLED_LINES`), PFC eligibility (`ERR_PFC_INELIGIBLE`), and the countersign deadline (`ERR_COUNTERSIGN_LAPSED`).

### 2.9. Nested Resource Retrieval

Many resources are addressed through their parents — a rate schedule beneath its fiscal year, a comment beneath its rate schedule, a settlement line beneath its settlement. For any such path, the system validates path identifiers sequentially from left to right and rejects the request with `404 Not Found` carrying `ERR_NOT_FOUND` at the *first* identifier that does not resolve to an existing resource; identifiers further to the right are never consulted once an earlier segment has failed. Existence inside the request body is a separate, later check: a body that names a carrier, fiscal year, capital project, or settlement that does not exist is rejected with `ERR_FK_NOT_FOUND`, and only after path validation has already succeeded.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both use the same rejection. Creating a rate schedule for a fiscal year requires the request to carry `expected_fiscal_year_version`, set to the `version` of the parent fiscal year as the client last observed it. If the year's current `version` no longer matches — for example because another writer has advanced the year since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Recomputing an annual settlement requires the request to carry `expected_annual_settlement_version`, set to the settlement's last-observed `version`; if the settlement's current `version` has since advanced — for instance after a dispute resolution rewrote its line amounts — the recompute is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two accepts an expected-version field.

### 2.11. Cascades and Automatic State Reconciliation

The system does not wait for clients to keep the hierarchy coherent. When a settlement is finalized, its parent fiscal year closes automatically, and any rate schedule still in `DRAFT` for that year expires in the same act. When a new rate schedule is published, the previously adopted schedule on the same year is superseded automatically. When a carrier's payment behavior crosses a line's due date, or when every open line for that carrier is cleared, the carrier's credit standing moves without anyone explicitly editing the agreement. Each such automatic reconciliation is a real mutation of the affected resource: `updated_at` is refreshed and `version` is incremented on every resource the cascade touches, so a client holding a stale view is caught by the concurrency rules of §2.10. A fiscal year that has reached `CLOSED` is sealed — every write scoped beneath it is refused with `ERR_FISCAL_YEAR_CLOSED`.

## 3. Business Logic & Workflows

### 3.1. Opening a Fiscal Year and Standing Up Carriers

A member of `AirportFinance` begins the annual cycle by creating a **FiscalYear**. The creation payload carries a `year_label` — a unique label such as FY2027 that is immutable after creation — together with the chosen `methodology`, the two cost pools `airfield_opex_cents` and `terminal_opex_cents`, the two revenue offsets `nonairline_airfield_revenue_cents` and `nonairline_terminal_revenue_cents`, the gross rentable `terminal_total_space_sqft`, and the airport's `forecast_landed_weight_kg` for the year. The carry-forward `prior_year_surplus_cents` is optional and defaults to zero; it may be negative, representing a deficit carried forward. The creation contract imposes no methodology restriction: a year of any methodology, `COMPENSATORY` included, accepts a supplied carry-forward and stores it on the year, with any exclusion applied later at derivation time per §2.7. Both cost pools and both revenue offsets must be non-negative integers, while the terminal square footage and the forecast landed weight must each be strictly positive. A new year begins in `DRAFT` status, with its computed aggregates `total_projected_landed_weight_kg`, `total_signatory_landed_weight_kg`, and `total_rented_space_sqft` initialized to zero and its `settlement_id` unset.

Opening the year is a distinct act performed by `AirportFinance`. The transition from `DRAFT` to `OPEN` requires that the methodology has been chosen and that the year's entry constraints hold — strictly positive terminal square footage and forecast landed weight, non-negative cost pools. A successful opening sets the year's `status` to `OPEN` and increments its `version`. The year later closes automatically when its settlement is finalized (§3.6), moving from `OPEN` to `CLOSED`; closure requires that a settlement exists — `settlement_id` set — and that the settlement stands `FINALIZED`. Once closed, no further activity records may be created for the year, a guard enforced by the year-closed rule of §2.11.

Carrier onboarding runs in parallel. `AirportFinance` registers each **Airline** with an `iata_code` — exactly two uppercase letters, unique across carriers — a `legal_name`, and a `carrier_class` of `PASSENGER`, `CARGO`, or `CHARTER`. The optional `pfc_approved` flag records whether the carrier holds FAA PFC collection approval at this airport and defaults to false when omitted. The carrier's `mii_eligible_weight_kg` is not an input; it is computed later, at the moment capital-project voting opens (§3.4).

With a year open and a carrier registered, `AirportFinance` creates an **AirlineAgreement** naming the `airline_id` and the `fiscal_year_id`, plus an optional `rented_space_sqft` for terminal space under exclusive or preferential lease, which must be non-negative when present. Every agreement begins with `signature_status` of `NON_SIGNATORY` and `credit_standing` of `GOOD`. These are two independent dimensions that evolve in parallel; an agreement has no terminal state. Throughout this document an agreement is called *active* when it has not been superseded — that is, while its `superseded_by_id` remains unset. Creation is implicitly a create-with-supersede: if the carrier already holds an active agreement on the same fiscal year, the earlier row's `superseded_by_id` is set to the new agreement's `id`, and the year's `total_rented_space_sqft` is recomputed. A superseded agreement is frozen — any attempt to mutate it, including a countersignature, is rejected with `ERR_AGREEMENT_SUPERSEDED`. One commercial invariant deserves emphasis: an agreement carrying a positive `rented_space_sqft` must ultimately stand `SIGNATORY`, because exclusive terminal space exists only under signatory status.

Countersigning is the carrier's own act. A `SignatoryAirline` user countersigns, moving the agreement's `signature_status` from `NON_SIGNATORY` to `SIGNATORY`, provided three conditions hold: the rate schedule for that fiscal year stands `ADOPTED`; the agreement's `credit_standing` is not `SUSPENDED`; and the logical clock has not passed the agreement's `countersign_deadline`. That deadline is not chosen at creation — it is stamped when the rate schedule is adopted, as `adopted_at` plus thirty days (§3.2). A countersignature arriving after the deadline is rejected with `ERR_COUNTERSIGN_LAPSED`, and countersigning an agreement that already stands `SIGNATORY` is rejected with `ERR_DOUBLE_COUNTERSIGN`. A successful countersign sets `signature_status` to `SIGNATORY`, recomputes the year's `total_rented_space_sqft` — the agreement's rented space now counts — and increments the agreement's `version`.

Signature standing can also be lost. A carrier may decline renewal, moving `signature_status` from `SIGNATORY` back to `NON_SIGNATORY`, and the system itself applies the same lapse when the logical clock moves past the `countersign_deadline` while the carrier still has an open settlement line whose `payment_status` is `PENDING` past its due date. Either path recomputes `total_rented_space_sqft` with the space no longer counted, increments the agreement's `version`, and triggers the voting exclusion cascade described in §3.4.

The credit dimension tracks settlement payment behavior. When the logical clock passes a settlement line's payment due date while that line still stands `PENDING`, the agreement's `credit_standing` moves from `GOOD` to `DELINQUENT` automatically. From `DELINQUENT`, `AirportFinance` may suspend the carrier — permitted only while at least one settlement line for that airline on that fiscal year remains `PENDING` — moving the standing to `SUSPENDED`. While `SUSPENDED`, the carrier is grounded for billing purposes: creating activity records or PFC applications for it is rejected with `ERR_AIRLINE_SUSPENDED`. Delinquency cures itself: once every open settlement line for the carrier stands `PAID` or `CREDITED`, the standing returns from `DELINQUENT` to `GOOD` automatically. A suspended carrier does not self-cure; `AirportFinance` must reinstate it, which is permitted only when no settlement line for that airline on that fiscal year remains `PENDING`, and returns the standing from `SUSPENDED` directly to `GOOD`. Each of these credit transitions increments the agreement's `version`.

### 3.2. Deriving, Consulting On, and Adopting the Rate Schedule

With a year open, `AirportFinance` creates a **RatesSetting** — the draft rate schedule — against that fiscal year. This is one of the two optimistic-concurrency-guarded writes of §2.10: the request must carry `expected_fiscal_year_version`, and a mismatch with the year's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The new schedule begins in `DRAFT`, and its creation increments the parent fiscal year's `version`. The schedule's computed fields — `airfield_requirement_cents`, `signatory_landing_fee_per_1000kg_cents`, `non_signatory_landing_fee_per_1000kg_cents`, and `terminal_rental_rate_per_sqft_year_cents` — are populated by the derivation rules below at creation, re-derived when the schedule is published, and re-derived again whenever the schedule is read, so a reader always sees rates consistent with the year's current inputs.

The airfield side of the derivation proceeds in a pinned order: first the requirement, then the denominator, then the signatory rate, then the non-signatory markup. The requirement depends on the year's methodology. Under a `RESIDUAL` year, `airfield_requirement_cents` is the airfield cost pool minus the non-airline airfield revenue offset plus the full `prior_year_surplus_cents`; because the carry-forward may be negative, a prior-year deficit raises the requirement just as a surplus lowers it. Under a `COMPENSATORY` year, the requirement is simply the airfield pool minus the non-airline offset, and the carry-forward is excluded in full. Under a `HYBRID` year, the requirement adds half of the carry-forward, with the halving rounded down to a whole cent — an odd negative balance rounds toward the more negative cent, so a deficit of −501 cents contributes −251 cents. In all three methodologies the denominator is the year's `forecast_landed_weight_kg`. The `signatory_landing_fee_per_1000kg_cents` is then the airfield requirement in cents multiplied by one thousand and divided by the forecast landed weight in kilograms, rounded half up to a whole cent. The `non_signatory_landing_fee_per_1000kg_cents` follows from it: the signatory fee scaled by 125 percent, rounded up to the next whole cent whenever the scaled value is not already exact.

The terminal side derives the space rate. The terminal requirement is `terminal_opex_cents` minus `nonairline_terminal_revenue_cents`, and the `terminal_rental_rate_per_sqft_year_cents` is that requirement divided by the year's `terminal_total_space_sqft`, rounded half up to a whole cent. An occupancy overlay rides on top of the published rate and is applied at charge time, not at rate time: when the year's `total_rented_space_sqft` reaches at least 85 percent of the gross rentable square footage, the airport grants a signatory-volume rebate equal to 5 percent of the portion of the terminal requirement attributable to signatory-rented space, reducing the effective requirement used when terminal charges are assessed.

Derivation can fail. If a divisor needed for the derivation is zero, or if the terminal rate multiplied by the aggregate rented square footage would exceed the terminal pool, then creating the schedule — and equally publishing it — is rejected with `ERR_RATE_NOT_DERIVABLE`.

Publication opens the consultation record. When `AirportFinance` publishes a schedule, it moves from `DRAFT` to `CONSULTATION`; the parent fiscal year must stand `OPEN`, and the computed rate fields must be populated. Publication zeroes the schedule's `consultation_comment_count` and increments the schedule's `version`. Publication is also the airport's mechanism for replacing a schedule mid-year: if another schedule on the same fiscal year currently stands `ADOPTED`, that schedule automatically transitions to `SUPERSEDED`, its `version` increments, and the active agreements keyed to it become supersession-eligible. During consultation, each carrier user may file a **ConsultationComment** against the schedule with a payload carrying the `airline_id` and a free-text `body`; each comment is stamped with `submitted_at`, carries its `rates_setting_id` back-reference, and increments the schedule's `consultation_comment_count` by one. Comments are immutable event records in the sense of §2.5.

Adoption belongs to the `AirportDirector`. A schedule in `CONSULTATION` may be adopted only once the logical clock has reached at least thirty days past the schedule's `created_at` — the minimum consultation period — and only while the parent fiscal year still stands `OPEN`; an adoption attempted before the window has elapsed is rejected with `ERR_TEMPORAL_VIOLATION`. Adoption stamps `adopted_at` with the current logical time, sets the schedule's status to `ADOPTED`, increments its `version`, and cascades to every active agreement on the fiscal year: each such agreement's `countersign_deadline` is stamped as `adopted_at` plus thirty days, with each cascaded agreement's `version` incremented as well.

For transparency, a reporting view of the adopted schedule also exposes the signatory differential: the non-signatory fee minus the signatory fee, multiplied by one hundred and divided by the signatory fee, rounded half up to two decimal places — the percentage premium a non-signatory carrier pays.

A schedule that never leaves the drafting table does not linger. If the parent fiscal year closes while a schedule still stands `DRAFT`, that schedule transitions automatically to `EXPIRED`. `SUPERSEDED` and `EXPIRED` are the terminal states of a rate schedule.

### 3.3. Recording Flight Activity and Billing Landing Fees

Throughout the open year, `AirportFinance` records each landing as an **ActivityRecord** beneath the fiscal year, providing the `airline_id`, the `activity_date`, the `landed_weight_kg` — the maximum certificated gross landing weight actually landed, strictly positive — and the `signature_status_at_activity`, a snapshot of whether the carrier stood `SIGNATORY` or `NON_SIGNATORY` on that date. The snapshot, not the carrier's present standing, drives the rate pick. The activity date must fall inside the fiscal year's own window as measured by the logical clock; a date outside it is rejected with `ERR_TEMPORAL_VIOLATION`.

The billed charge is stamped at creation and never recomputed afterwards. The landed weight is broken into whole units of one thousand kilograms; a remainder of at least five hundred kilograms is rounded up as one additional full unit, while a smaller remainder is discarded — so a record landing exactly 1,499 kilograms bills a single unit, a record at exactly 1,500 kilograms bills two, and a remainder sitting exactly on the five-hundred-kilogram boundary always rounds up. The per-unit rate is the adopted schedule's signatory fee when `signature_status_at_activity` is `SIGNATORY` and the non-signatory fee otherwise. The resulting `billed_landing_fee_cents` is the number of charge units multiplied by that per-unit rate, in whole cents.

Two aggregates follow every insertion. The year's `total_projected_landed_weight_kg` is recomputed as the sum of `landed_weight_kg` across all of the year's activity records, and whenever the record's snapshot status is `SIGNATORY` the year's `total_signatory_landed_weight_kg` is recomputed as the sum over signatory-snapshot records only.

Two guards stand in front of activity creation, and their order is fixed by §2.8. The fiscal year must still stand `OPEN`; a record filed against a `CLOSED` year is rejected with `ERR_FISCAL_YEAR_CLOSED`, and this year-level guard is evaluated before the carrier-level one, so a filing that trips both reports the closed year. If the carrier's agreement stands `SUSPENDED`, creation is rejected with `ERR_AIRLINE_SUSPENDED`. Like comments and votes, activity records are immutable event records carrying only `id` and `created_at` among the common properties.

### 3.4. Capital Projects and Majority-in-Interest Voting

Capital spending above the routine level requires the signatory carriers' consent, administered here as a **CapitalProject** with a two-leg majority-in-interest vote. `AirportFinance` proposes a project beneath an open fiscal year, supplying the `project_name`, the `cost_center` — `AIRFIELD` or `TERMINAL`, naming the pool that would absorb the cost — a `budget_cents` that must be strictly positive, and the `mii_threshold_pct`, the approval threshold percent applied to both the count leg and the weight leg, which must be at least 50 and at most 100. A new project stands `PROPOSED`, with its tallies `votes_for_count`, `votes_for_weight_kg`, and `votes_against_weight_kg` at zero.

Opening the vote is an explicit act by `AirportFinance`, permitted only while the parent fiscal year stands `OPEN`. The project moves from `PROPOSED` to `MII_VOTING`, all three tallies are reset to zero, the project's `version` increments, and — critically — each eligible carrier's voting weight is frozen at this moment: for every signatory airline, the server recomputes `mii_eligible_weight_kg` from that carrier's landed-weight activity over the rolling twelve-month window and snapshots it onto the `Airline` record. From then until the decision, the electorate and its weights are fixed: the eligible voters are the distinct airlines holding an active agreement in `SIGNATORY` standing on the fiscal year at the moment of tally, and each voter's weight is its snapshotted `mii_eligible_weight_kg`.

A carrier user casts a ballot by submitting its `airline_id` and a `ballot` of `APPROVE` or `REJECT`; the vote is stamped with `cast_at` and carries its `capital_project_id` back-reference. A ballot aimed at a project that has not yet opened for voting — one still standing `PROPOSED` — is rejected earlier, at the current-state check of §2.8, with `ERR_INVALID_STATE`, before the business-rule rejections below are consulted. Three rejections guard the ballot box, and they are evaluated in a fixed order. Eligibility is checked first: a carrier without an active, signatory agreement on the parent fiscal year is refused with `ERR_NOT_SIGNATORY`. Uniqueness is checked second: a carrier that has already voted on this project — at most one vote per carrier per project — is refused with `ERR_DUPLICATE_VOTE`. Only if both pass does the server ask whether the project still accepts votes: a ballot aimed at a project already `APPROVED`, `VETOED`, `REJECTED`, or `CANCELLED` is refused with `ERR_PROJECT_ALREADY_DECIDED`. The ordering matters — a repeat ballot on an already-decided project reports the duplicate, not the closed project.

Every accepted ballot recomputes the tally and can decide the project on the spot. Approval requires both legs to pass: the number of distinct approving carriers multiplied by one hundred must be at least the threshold percent times the total number of eligible signatory carriers, and the approving weight multiplied by one hundred must be at least the threshold percent times the total eligible signatory weight. The boundary is inclusive on both legs — a tally landing exactly at the threshold approves the project, moving it from `MII_VOTING` to `APPROVED`. The veto leg runs on weight alone: if the rejecting weight multiplied by one hundred exceeds the complementary share — one hundred minus the threshold percent — of the total eligible signatory weight, the project moves from `MII_VOTING` to `VETOED`. The veto boundary is exclusive: rejecting weight landing exactly on the complementary threshold does not veto and leaves the project open. Either automatic decision seals the ballot box, so subsequent ballots draw `ERR_PROJECT_ALREADY_DECIDED` per the ordering above.

If voting runs its course without either automatic threshold being reached, `AirportFinance` closes the vote and the project moves from `MII_VOTING` to `REJECTED` — closure is permitted precisely when neither the approval nor the veto threshold was reached during open voting. A project that has not yet opened for voting may instead be withdrawn: cancellation moves a `PROPOSED` project to `CANCELLED`. `APPROVED`, `REJECTED`, `VETOED`, and `CANCELLED` are all terminal.

Signature standing and voting interact in one more direction. When a carrier's agreement lapses or the carrier declines renewal — the `SIGNATORY` to `NON_SIGNATORY` moves of §3.1 — any `APPROVE` ballot that carrier has cast on a project still in `MII_VOTING` is excluded from the recomputation of both `votes_for_count` and `votes_for_weight_kg`. An airline that walks away from the agreement cannot carry its endorsement into a decision it will not be bound by.

### 3.5. Computing the Annual Settlement

When the year's activity is in, `AirportFinance` computes the **AnnualSettlement** for the fiscal year. Computation requires the year to stand `OPEN` and at least one activity record to exist for it; with no activity at all the attempt is rejected with `ERR_NO_ACTIVITY`. A successful computation runs the true-up waterfall below, creates one **AirlineSettlementLine** per airline that had any activity or any rented space during the year, sets the year's `settlement_id` to the new settlement — making the settlement reverse-reachable from the year — and increments the `version` of both the settlement and the fiscal year. The settlement begins in `DRAFT` and stands `COMPUTED` once the computation completes.

The waterfall rebuilds the requirements against actuals. The `actual_airfield_requirement_cents` is the airfield pool minus the non-airline airfield offset, plus the carry-forward in full when the year is `RESIDUAL`. The signatory pool weight is the sum of `landed_weight_kg` over the year's activity records whose snapshot status is `SIGNATORY`, and each signatory carrier's `actual_airfield_share_cents` is the actual airfield requirement multiplied by that carrier's own signatory-snapshot landed weight and divided by the signatory pool weight, rounded half up to a whole cent. Non-signatory carriers receive no airfield share and owe no residual true-up — they already paid the markup at charge time. On the building side, the `actual_terminal_requirement_cents` is the terminal pool minus the non-airline terminal offset, and each carrier holding an active agreement receives an `actual_terminal_share_cents` equal to that requirement multiplied by the agreement's `rented_space_sqft` and divided by the year's `total_rented_space_sqft`, rounded half up to a whole cent.

Per-line rounding can drift from the requirement by a few cents, and the drift is reconciled rather than absorbed. After every airfield share is rounded, the difference between their sum and the actual airfield requirement is allocated, cent for cent, to the carrier with the largest signatory-snapshot landed weight; the terminal shares are reconciled the same way, with the difference allocated to the carrier with the largest rented square footage. Ties on either side are broken in favor of the carrier whose `Airline` record has the earliest `created_at`.

Each line's `true_up_cents` is then the sum of its `actual_airfield_share_cents` and `actual_terminal_share_cents` minus the sum of what the carrier was already billed — its `billed_landing_cents` and `billed_terminal_cents`. A positive figure means the airline owes the airport; a negative figure means the airport credits the airline, applied as a `CREDITED` line when the credit is taken. At the settlement level, `total_billed_landing_cents` is the sum of `billed_landing_fee_cents` across the year's activity records, `total_billed_terminal_cents` is the sum over active agreements of `rented_space_sqft` multiplied by the adopted terminal rate, and `total_true_up_cents` is the sum of the lines' `true_up_cents`. One invariant must always hold: `total_true_up_cents` equals the sum of `actual_airfield_requirement_cents` and `actual_terminal_requirement_cents` minus the sum of `total_billed_landing_cents` and `total_billed_terminal_cents`. This compensating invariant is what makes a later recompute safe.

The waterfall has two modes. While the year stands `OPEN` and activity may still arrive, a provisional estimate uses the forecast landed weight in its denominators, performs no remainder reconciliation, and persists no settlement lines — it exists for budget preview only. The final actual computation runs once the year's records are complete, uses the actual signatory pool weight and the actual rented space in its denominators, applies the remainder reconciliation, and persists the lines.

A computed settlement can be recomputed against the year's current activity records. This is the second optimistic-concurrency-guarded write of §2.10: the request must carry `expected_annual_settlement_version` matching the settlement's current `version`, and a mismatch — for instance after a director's dispute resolution has rewritten the line amounts since the client last read the settlement — is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful recompute rewrites the computed fields of every settlement line, preserves the settlement-level total through the compensating invariant modulo the explicit rounding remainder, and increments the settlement's `version`.

### 3.6. Review, Dispute, Payment, and Finalization

A computed settlement is published to the carriers by `AirportFinance`, moving from `COMPUTED` to `AIRLINE_REVIEW`. Publication stamps every line's `payment_status` to `PENDING` and stamps a sixty-day payment due date on each line — the due date against which the delinquency automation of §3.1 later runs.

A carrier that disagrees may dispute. The dispute is filed by a `SignatoryAirline` user with the carrier's `airline_id` and a free-text `reason`, and it is only open to a carrier that actually has a settlement line in this settlement. The first dispute must be raised within forty-five days of the publish-review action; a dispute raised after that window is refused with `ERR_DISPUTE_WINDOW_EXPIRED`. A valid dispute moves the settlement from `AIRLINE_REVIEW` to `DISPUTED`.

Resolution belongs to the `AirportDirector`. Resolving moves the settlement from `DISPUTED` to `RESOLVED`. The director may attach an `override_true_up_cents` figure; when the override is present, the affected lines' `true_up_cents` are rewritten following the same allocation waterfall, and the `payment_status` of the affected lines is reset to `PENDING` so the corrected amounts re-enter collection. When no override is present, the system-recomputed true-up amounts stand as they are.

The cycle is deliberately not one-shot. A carrier whose concerns survive resolution may dispute again: a further dispute moves the settlement from `RESOLVED` back to `DISPUTED`, provided it is raised within forty-five days of the most recent resolve and the carrier holds a line in the settlement; a reopening attempted after that window is refused with `ERR_DISPUTE_WINDOW_EXPIRED`. Dispute and resolution can iterate until the amounts settle.

Collection runs line by line. `AirportFinance` records payment against a line by submitting an `outcome`: the line is marked `PAID` when an airline-owed amount is collected, or `CREDITED` when an airport-owed amount is applied as a credit. When a carrier's last remaining `PENDING` line on the fiscal year clears, the agreement's credit standing recovers from `DELINQUENT` to `GOOD` automatically, per §3.1. An uncollectible line is instead written off by the `AirportDirector`, setting its `payment_status` to `WRITTEN_OFF`; note that a write-off satisfies the finalization gate below but does not by itself cure a delinquency, which recovers only through `PAID` or `CREDITED` lines.

Finalization closes the books. The `AirportDirector` may finalize a settlement standing either `AIRLINE_REVIEW` or `RESOLVED`, and the gate is the same from both: no settlement line may remain `PENDING` — every line must stand `PAID`, `CREDITED`, or `WRITTEN_OFF` — else the attempt is rejected with `ERR_UNSETTLED_LINES`. Finalization sets the settlement to its terminal `FINALIZED` status and cascades twice: the parent fiscal year moves from `OPEN` to `CLOSED`, and any rate schedule on that year still standing `DRAFT` moves to `EXPIRED`. The year's closure in turn seals it against further activity records and all other year-scoped writes under the year-closed guard.

### 3.7. Passenger Facility Charge Remittance

Carriers holding FAA collection approval remit Passenger Facility Charges through a **PFCApplication** filed beneath the fiscal year. The carrier user submits the `airline_id` and the `enplaned_passengers` count — the number of revenue enplaned passengers subject to the charge, which must be non-negative. Eligibility is strict: the carrier's `carrier_class` must be `PASSENGER` and its `pfc_approved` flag must be true, and anything short of both is rejected with `ERR_PFC_INELIGIBLE`; the parent fiscal year must also still stand `OPEN`, and a suspended carrier is turned away under the suspension guard with `ERR_AIRLINE_SUSPENDED`. A valid application begins in `SUBMITTED` status.

The collectible amount is computed at submission and stored as `pfc_amount_cents`: the enplaned passenger count multiplied by 450 cents per passenger — a $4.50 charge — except that passengers beyond the annual cap are not collectible, so the multiplication uses the lesser of the reported count and an annual cap of 2,000,000 enplaned passengers.

Disposition belongs to the `AirportDirector`, who decides the application by submitting a `decision`. Acceptance moves the application from `SUBMITTED` to `ACCEPTED`. Rejection moves it from `SUBMITTED` to `REJECTED` and records the supplied `rejection_reason` on the application; that field is populated precisely when the status is `REJECTED` and remains unset otherwise.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that read resources, transition a resource between states, or otherwise modify an existing resource return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/airport/_clock/set_current_utc` | Set the server's logical clock | AirportFinance, AirportDirector |
| POST | `/airport/fiscal_years` | Create a fiscal year in `DRAFT` | AirportFinance |
| GET | `/airport/fiscal_years` | List fiscal years, paginated | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/fiscal_years/{id}` | Get one fiscal year | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/fiscal_years/{id}/open` | Transition a fiscal year from `DRAFT` to `OPEN` | AirportFinance |
| POST | `/airport/airlines` | Register an airline | AirportFinance |
| GET | `/airport/airlines` | List airlines, paginated | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}` | Get one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/agreements` | List the agreements belonging to one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/airline_agreements` | Create an agreement, superseding any prior active agreement for the same carrier and year | AirportFinance |
| GET | `/airport/airline_agreements/{id}` | Get one agreement | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/airline_agreements/{id}/countersign` | Carrier countersigns: `NON_SIGNATORY` to `SIGNATORY` | SignatoryAirline |
| POST | `/airport/airline_agreements/{id}/decline-renewal` | Carrier declines: `SIGNATORY` to `NON_SIGNATORY` | SignatoryAirline |
| POST | `/airport/airline_agreements/{id}/suspend` | Suspend a delinquent carrier | AirportFinance |
| POST | `/airport/airline_agreements/{id}/reinstate` | Reinstate a suspended carrier once no pending lines remain | AirportFinance |
| POST | `/airport/fiscal_years/{id}/rates_settings` | Create a draft rate schedule for the year, OCC-guarded on the year's version | AirportFinance |
| GET | `/airport/rates_settings/{id}` | Get one rate schedule | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/fiscal_years/{id}/rates_settings` | List the rate schedules of one fiscal year | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/rates_settings/{id}/publish` | Move a schedule from `DRAFT` to `CONSULTATION`, superseding any adopted schedule on the year | AirportFinance |
| POST | `/airport/rates_settings/{id}/adopt` | Move a schedule from `CONSULTATION` to `ADOPTED` once the consultation window has elapsed | AirportDirector |
| POST | `/airport/rates_settings/{id}/comments` | File a consultation comment on a schedule | SignatoryAirline |
| GET | `/airport/rates_settings/{id}/comments` | List the comments on a schedule | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/fiscal_years/{id}/activity_records` | Record one landed-weight activity, stamping its billed landing fee | AirportFinance |
| GET | `/airport/fiscal_years/{id}/activity_records` | List a fiscal year's activity records | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/fiscal_years/{id}/capital_projects` | Propose a capital project | AirportFinance |
| GET | `/airport/capital_projects/{id}` | Get one capital project | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/capital_projects/{id}/open-voting` | Move a project from `PROPOSED` to `MII_VOTING`, snapshotting voting weights | AirportFinance |
| POST | `/airport/capital_projects/{id}/close-voting` | Close voting with no threshold reached, moving the project to `REJECTED` | AirportFinance |
| POST | `/airport/capital_projects/{id}/cancel` | Cancel a `PROPOSED` project | AirportFinance |
| POST | `/airport/capital_projects/{id}/mii_votes` | Cast a majority-in-interest vote | SignatoryAirline |
| GET | `/airport/capital_projects/{id}/mii_votes` | List the votes on a project | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/fiscal_years/{id}/settlement/compute` | Compute the year's settlement, running the true-up and creating per-airline lines | AirportFinance |
| GET | `/airport/settlements/{id}` | Get one annual settlement | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/settlements/{id}/publish-review` | Move a settlement from `COMPUTED` to `AIRLINE_REVIEW`, stamping payment due dates | AirportFinance |
| POST | `/airport/settlements/{id}/dispute` | Dispute a settlement under review, or reopen a resolved one inside the window | SignatoryAirline |
| POST | `/airport/settlements/{id}/resolve` | Resolve a dispute, optionally overriding the true-up allocation | AirportDirector |
| POST | `/airport/settlements/{id}/recompute` | Re-run the true-up against current activity, OCC-guarded on the settlement's version | AirportFinance |
| POST | `/airport/settlements/{id}/finalize` | Finalize a settlement, closing the year and expiring draft schedules | AirportDirector |
| GET | `/airport/settlements/{id}/lines` | List the per-airline lines of a settlement | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/settlement_lines/{id}/record-payment` | Mark a line `PAID` or `CREDITED`, recovering credit standing when the last pending line clears | AirportFinance |
| POST | `/airport/settlement_lines/{id}/write-off` | Mark a line `WRITTEN_OFF` as uncollectible | AirportDirector |
| POST | `/airport/fiscal_years/{id}/pfc_applications` | Submit a PFC remittance application | SignatoryAirline |
| GET | `/airport/fiscal_years/{id}/pfc_applications` | List a fiscal year's PFC applications | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/pfc_applications/{id}` | Get one PFC application | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/pfc_applications` | List the PFC applications filed by one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| POST | `/airport/pfc_applications/{id}/decide` | Accept or reject a PFC application | AirportDirector |
| GET | `/airport/consultation_comments/{id}` | Get one consultation comment | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/activity_records/{id}` | Get one activity record | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/mii_votes/{id}` | Get one MII vote | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/settlement_lines/{id}` | Get one settlement line | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/fiscal_years/{id}/agreements` | List the agreements keyed to one fiscal year | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airline_agreements/{id}/successors` | List the agreements that superseded this one | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/comments` | List the consultation comments filed by one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/activity_records` | List the activity records of one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/fiscal_years/{id}/capital_projects` | List the capital projects of one fiscal year | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/mii_votes` | List the MII votes cast by one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/fiscal_years/{id}/settlement` | List the annual settlement of one fiscal year — an array of length zero or one | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |
| GET | `/airport/airlines/{id}/settlement_lines` | List the settlement lines belonging to one airline | AirportFinance, AirportDirector, SignatoryAirline, AirportAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TEMPORAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_FISCAL_YEAR_CLOSED` | 409 Conflict |
| `ERR_AIRLINE_SUSPENDED` | 409 Conflict |
| `ERR_NOT_SIGNATORY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_PROJECT_ALREADY_DECIDED` | 409 Conflict |
| `ERR_RATE_NOT_DERIVABLE` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVITY` | 422 Unprocessable Entity |
| `ERR_UNSETTLED_LINES` | 409 Conflict |
| `ERR_PFC_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_COUNTERSIGN_LAPSED` | 422 Unprocessable Entity |
| `ERR_METHODOLOGY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_SUPERSEDED` | 409 Conflict |
| `ERR_DOUBLE_COUNTERSIGN` | 409 Conflict |
