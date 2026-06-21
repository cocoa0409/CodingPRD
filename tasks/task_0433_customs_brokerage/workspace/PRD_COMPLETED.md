# Customs Brokerage & Import Compliance API — Product Requirements Document

## 1. Introduction

This document specifies a backend service for U.S. customs brokerage and import compliance, modelled on the workflow a licensed broker drives through CBP's Automated Commercial Environment. The system carries a shipment from the moment an importer of record is onboarded, through the advance security filing and the formal entry summary, into CBP review and physical examination, and finally to liquidation and any post-summary correction or protest. It is built for four distinct user populations whose duties are deliberately kept apart: an operational administrator who provisions importers, bonds, and billing periods; importers of record acting for their own account; licensed brokers who classify merchandise and file on behalf of importers; and CBP officers who review, release, examine, liquidate, and adjudicate.

The central difficulty the product solves is fiscal and procedural reconciliation. Every entry is priced twice — once provisionally at filing, when the broker's preference claims are taken on trust, and once finally at liquidation, when those claims are verified against the country of origin and the partner-government-agency outcomes are known. The difference between the two figures ripples outward: it adjusts the liability secured by the importer's bond, which can saturate or recover; it re-totals the periodic monthly statement the entry rolls up onto; and, after liquidation, it can be reopened by a correction or protest that supersedes the entry's prior fiscal state. Because money, custody, and legal authority all move together, the specification is exacting about ordering, about which actor may act when, and about the exact arithmetic of duty, fees, and tax. All monetary amounts in this system are integer cents; the API never traffics in fractional currency.

A logical server clock governs every time-sensitive rule — the advance-filing cutoff and the calendar month an entry is billed into both read from it — so that behaviour is deterministic and testable rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role under which the call is made. If either header is missing, or if `X-User-Role` is not one of the four roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly as follows:

- **`AccountAdmin`** — the operational administrator. Sets up importers and bonds, opens and settles monthly statements, and advances the system clock. `X-User-ID` for an `AccountAdmin` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`ImporterUser`** — an importer of record acting for its own account. This role is entity-backed: when `X-User-Role` is `ImporterUser`, `X-User-ID` is the `id`-equivalent owner key of the acting importer, and ownership checks compare an importer's `owner_user_id` field to `X-User-ID`. An `ImporterUser` may draft ISF filings, entries, and lines and submit post-summary corrections only for an importer whose `owner_user_id` equals its `X-User-ID`; acting against any other importer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- **`LicensedBroker`** — a licensed customs broker. Classifies merchandise, files ISFs and entries, opens partner-government-agency reviews, and submits corrections and protests on behalf of importers. `X-User-ID` for a `LicensedBroker` is an opaque operator identifier not tied to any persisted entity; the server records it as `filed_by_user_id` on an entry when the broker files it, but does not otherwise compare it to any entity's `id`.
- **`CBPOfficer`** — a CBP officer. Reviews, releases, and holds entries; records agency decisions; books and cancels examination slots; liquidates entries; and grants or denies corrections and protests. `X-User-ID` for a `CBPOfficer` is an opaque operator identifier not tied to any persisted entity; the server records it as `reviewed_by_user_id` on an entry or review when the officer acts, but does not compare it to any entity's `id`.

The complete mapping of operations to authorized roles is given by the endpoint table in §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and has no upper bound beyond the size of the collection. List results are always sorted by `created_at` in ascending order. For every list response, the `meta` block carries the effective `limit`, the effective `offset`, the `total_count` of records matching the query before pagination, and a `has_more` boolean that is true exactly when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, fixed at creation. All nine entities in this system — Importer, Bond, ISFFiling, CustomsEntry, EntryLine, PGAReview, ExamSlot, MonthlyStatement, and PostSummaryCorrection — additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 on creation and increments by exactly 1 on every mutation that the system records as a version bump; `updated_at` is refreshed to the current clock instant on each such mutation. Where a workflow below states that an operation "increments the version" of an entity, it is this counter that advances and this timestamp that is refreshed.

### 2.5. Monetary Precision and Rounding

All amounts are integer cents. Two arithmetic conventions are fixed across the system. First, the rounding mode everywhere a fractional cent could arise is round half up to the nearest integer cent. Second, when line-level duties are aggregated, the rounding happens per line and only then are the rounded line figures summed — the system rounds each line's duty to an integer cent first and adds those integers, never the reverse of summing exact values and rounding once at the end. This round-per-line-then-sum order is pinned and is observable wherever multiple lines contribute to an entry's duty total.

### 2.6. Left-to-Right Reference Resolution

Several resources are addressed through nested paths or reference other resources by foreign key in their request body. Before any business rule is evaluated, every referenced resource — whether named in the URL path or carried as a foreign key in the body — must exist; references are checked left to right, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). For example, when listing or fetching the lines of an entry, the entry in the path is resolved before the line scope is considered.

### 2.7. Optimistic Concurrency on Post-Summary Filings

A liquidated entry can be reopened more than once — a later correction legitimately supersedes the fiscal state a prior liquidation or a prior granted correction left behind — so the system serializes these filings on the entry's `version` rather than on wall-clock arrival order. Submitting a post-summary correction or protest requires the field `expected_entry_version`, which must carry the `version` of the target entry as the client last observed it. If that value does not equal the entry's current `version` — because an earlier liquidation or an earlier granted correction has since advanced it — the submission is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412), preventing the filer from acting against a fiscal state it has not seen. No other endpoint in this system takes a version field.

### 2.8. Validation Ordering

When several conditions could fail a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or unknown header pair yields `ERR_UNAUTHENTICATED` before anything else. Authorization by role is checked next, yielding `ERR_UNAUTHORIZED`. Existence of every path and foreign-key reference is checked third, yielding `ERR_NOT_FOUND`. Resource ownership for an `ImporterUser` is checked fourth, yielding `ERR_NOT_RESOURCE_OWNER`. The target resource's state for the requested transition is checked fifth, yielding `ERR_INVALID_STATE`. Segregation of duties is checked sixth. Beyond these, the remaining business, fiscal, and temporal rules described throughout §3 are applied; where two such rules could both fire on one request, the lower-numbered rule in the error catalogue's narrative ordering — for instance, a bond-importer mismatch before a bond-insufficiency check, and an insufficiency rejection before a saturation rejection — takes precedence. Basic input validation — a required field absent or a value failing a simple type or range check, such as a non-positive `customs_value_cents` or a `data_element_count` outside the range 0 through 10 — yields `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Onboarding the Importer and Its Bond

Everything in this system hangs off an **importer of record**, created by an `AccountAdmin`. Creation supplies the importer's legal `name`, which must be non-empty; its `ior_number`, the Importer of Record number that must be non-empty and unique across all importers; and the `owner_user_id`, the opaque identifier of the `ImporterUser` who will own and act on the record. A new importer starts with `status` of `ACTIVE` (the only other value being `SUSPENDED`) and a `continuous_bond_id` of null. Attempting to reuse an `ior_number` already held by another importer is rejected with `ERR_DUPLICATE` (HTTP 409). Importers can be fetched individually and listed; the list view may be narrowed with the `owner_user_id` and `continuous_bond_id` query filters.

A **bond** secures an importer's potential liability to CBP and must exist and be active before any entry can be filed. An `AccountAdmin` creates a bond by supplying the `importer_id` it secures, a `bond_type` of either `CONTINUOUS` or `SINGLE_ENTRY`, and a `limit_cents` ceiling that must be at least 0. A freshly created bond has `status` of `PENDING`, an `outstanding_liability_cents` of 0, and no securing effect yet. Bonds may be fetched and listed, the list optionally filtered by `importer_id`.

Activating a bond moves it from `PENDING` to `ACTIVE`; this is permitted only while the bond is `PENDING` and its `limit_cents` is at least 0. On activation, if the bond's `bond_type` is `CONTINUOUS`, the securing importer's `continuous_bond_id` is set to point at this bond, recording it as the importer's most recently activated continuous bond; activation increments the bond's version. Only an `ACTIVE` bond may secure a filing. A bond reaches `SATURATED` automatically — not by any direct call — when, after an entry-filing reconciliation, its `outstanding_liability_cents` becomes greater than or equal to its `limit_cents`; while saturated, further filings against it are refused. The reverse transition is also automatic: when a later liquidation or correction reconciliation drops its `outstanding_liability_cents` strictly below its `limit_cents`, a `SATURATED` bond returns to `ACTIVE`. Terminating a bond moves it from `ACTIVE` to the terminal `TERMINATED` state; this is allowed only while the bond is `ACTIVE` and its `outstanding_liability_cents` is exactly 0. Termination clears the importer's `continuous_bond_id` back to null if and only if it currently points at the bond being terminated, and increments the bond's version.

### 3.2. The Advance Security Filing (ISF, 10+2)

Before merchandise arrives, the importer's advance security filing — the **ISF** — must be on file. An `ImporterUser` or a `LicensedBroker` drafts one by supplying the `importer_id` it is filed for, the ocean `bill_of_lading` it binds to, the scheduled `vessel_eta` (the vessel's estimated arrival at the U.S. port, an ISO 8601 UTC instant), and the `data_element_count`, the number of the ten importer data elements supplied, which must be an integer from 0 through 10. A new ISF starts in `DRAFT` `status` with `filed_at` null and `late_filing` false. The `bill_of_lading` must be unique across all ISF filings; a duplicate is rejected with `ERR_DUPLICATE` (HTTP 409). ISF filings may be fetched and listed, the list optionally filtered by `importer_id`.

A `LicensedBroker` files a draft ISF, advancing it from `DRAFT` to `FILED`. This is permitted only while the ISF is in `DRAFT` and all ten importer data elements are present — that is, `data_element_count` equals exactly 10; an attempt with any other count is rejected with `ERR_ISF_INCOMPLETE` (HTTP 422). On filing, the server stamps `filed_at` with the current logical clock instant and computes `late_filing`: the filing is late, and `late_filing` is set true, exactly when `filed_at` is strictly later than the moment 24 hours before the `vessel_eta`; if `filed_at` is at or before that cutoff, `late_filing` is false. (The advance-filing cutoff is 24 hours ahead of the vessel's estimated arrival.) Filing sets the ISF `status` to `FILED` and increments its version. A `LicensedBroker` may instead cancel a draft, moving it from `DRAFT` to the terminal `CANCELLED` state and incrementing its version; cancellation is permitted only while the ISF is in `DRAFT`. The remaining terminal state, `MATCHED`, is never reached by a direct call — it is driven by entry release, as described in §3.5.

### 3.3. Drafting the Entry and Classifying Its Lines

A **customs entry** — the entry summary, the 7501 — is the fiscal heart of the system. An `ImporterUser` or a `LicensedBroker` creates one in `DRAFT` by supplying the `importer_id` of record, the `bond_id` that will secure it, an optional `isf_filing_id` (which may be null at draft time but must be set and matched before release), the `entry_type` (one of `CONSUMPTION_01`, `WAREHOUSE_21`, or `FTZ_06`), the two-letter uppercase ISO `country_of_origin`, and the declared `entry_date`, an ISO 8601 UTC instant used to anchor the duty epoch. A new entry begins in `DRAFT` `status` with its `provisional_total_cents` and `total_duties_owed_cents` at 0, its `final_total_cents` null, and its `filed_by_user_id`, `reviewed_by_user_id`, and `statement_id` all null. The `country_of_origin` must be exactly two uppercase letters; a malformed value is rejected with `ERR_INVALID_FORMAT` (HTTP 422). Entries may be fetched and listed; the list may be filtered by `importer_id`, `bond_id`, `isf_filing_id`, or `statement_id`.

While an entry is in `DRAFT`, lines are added to it; lines may only be added while the entry is `DRAFT`. Each **entry line** is created against its parent through the entry-scoped line path and supplies the `hts_code` — a ten-digit Harmonized Tariff Schedule classification — together with the declared `customs_value_cents` (which must be strictly greater than 0), the optional `assists_cents` of dutiable additions such as assists, royalties, and packing (defaulting to 0 and never negative), the `quantity` of units (which must be strictly greater than 0), an optional `preference_claim` of either `NONE` (the default) or `USMCA`, and an optional `pga_flag` of `NONE` (the default), `FDA`, or `USDA` naming the partner government agency whose jurisdiction the line falls under. The `entry_id` foreign key carried on each line names the parent entry. The `hts_code` must be exactly ten digits; a value that is not is rejected with `ERR_INVALID_FORMAT` (HTTP 422).

At the moment a line is created the system computes its **dutiable value**: the line's `dutiable_value_cents` equals its `customs_value_cents` plus its `assists_cents`. Because both inputs are already integer cents, no rounding is involved. A new line's `line_duty_cents` is 0 and its `preference_verified` is false until the entry is priced. The `dutiable_value_cents` is recomputed from the same sum when the entry is filed.

### 3.4. Filing the Entry — Provisional Pricing and Bond Reconciliation

A `LicensedBroker` files an entry, advancing it from `DRAFT` to `FILED`. Filing is the gate at which the entry's provisional charges are computed and the bond is first encumbered, so its preconditions are the most demanding in the system. The entry must be in `DRAFT`; it must carry at least one line, or the request is rejected with `ERR_NO_LINES` (HTTP 422); the bond named by `bond_id` must be in `ACTIVE` status — a bond that is in any non-securing state other than `SATURATED` (for instance `PENDING` or `TERMINATED`) is rejected with `ERR_INVALID_STATE` (HTTP 409), the `SATURATED` case being handled by `ERR_BOND_SATURATED` below; the `isf_filing_id` must be set and the referenced ISF must be in `FILED` status, failing which the rejection is `ERR_ISF_NOT_FILED` (HTTP 409); and for every line whose `pga_flag` is not `NONE`, a partner-government-agency review must already exist for that entry and that agency, the absence of which is rejected with `ERR_INVALID_STATE` (HTTP 409).

Two referential and temporal guards apply specifically at filing. The bond securing the entry must belong to the same importer as the entry — its `importer_id` must equal the entry's `importer_id` — or the filing is rejected with `ERR_BOND_IMPORTER_MISMATCH` (HTTP 422). And the entry's `entry_date` must not be earlier than the referenced ISF's `vessel_eta` minus 24 hours; an entry date that precedes that manifest cutoff is rejected with `ERR_ENTRY_PRECEDES_MANIFEST` (HTTP 422).

When the preconditions hold, the system prices the entry provisionally. Each line's `dutiable_value_cents` and `line_duty_cents` are computed under the provisional rule. A line's base duty is its `dutiable_value_cents` multiplied by a rate in basis points, divided by 10000, rounded half up to an integer cent. The rate is selected by the first two digits of the line's `hts_code`, read as the tariff chapter: chapter "61" or "62" (apparel) uses 1650 basis points; chapter "84" or "85" (machinery and electronics) uses 250 basis points; any other chapter uses the general rate of 500 basis points. In the provisional variant a `USMCA` preference claim is trusted unconditionally — any line whose `preference_claim` is `USMCA` has its `line_duty_cents` set to 0 regardless of the entry's country of origin — while a line with no preference takes its base duty as `line_duty_cents`.

The entry's provisional grand total is then assembled in a pinned order and stored as `provisional_total_cents`. First, the total dutiable value is the sum across all lines of `dutiable_value_cents`. Second, the total duty is the sum across all lines of the per-line `line_duty_cents` already rounded in the previous step. Third, the merchandise processing fee is computed ad valorem with a floor and a ceiling: a raw figure equal to the total dutiable value multiplied by 35 basis points, divided by 10000, rounded half up; the fee is then the raw figure clamped to be no less than 3215 cents and no more than 62333 cents — that is, the larger of 3215 and the raw figure, then the smaller of that and 62333. The merchandise processing fee is waived entirely, set to 0, when every line on the entry carries a verified preference for the variant being computed; in the provisional variant that means every line claims `USMCA`. Fourth, the harbor maintenance fee applies to every entry whose `entry_type` is not `FTZ_06`: it equals the total dutiable value multiplied by 13 basis points, divided by 10000, rounded half up, with no cap; for an `FTZ_06` entry the harbor maintenance fee is 0. Fifth, a tax component applies when any line on the entry has a `pga_flag` of `FDA`, serving as an excise proxy: it equals the total dutiable value multiplied by 200 basis points, divided by 10000, rounded half up; if no line is `FDA`-flagged the tax is 0. Sixth, the grand total is the total duty plus the merchandise processing fee plus the harbor maintenance fee plus the tax.

Filing then sets `total_duties_owed_cents` equal to `provisional_total_cents`, stamps `filed_by_user_id` with the calling broker's `X-User-ID`, sets the entry `status` to `FILED`, and increments the entry's version. As a cascade, the securing bond's `outstanding_liability_cents` is increased by the entry's `total_duties_owed_cents`; if that reconciliation brings the bond's outstanding liability up to or past its `limit_cents`, the bond auto-transitions from `ACTIVE` to `SATURATED`. Two fiscal guards protect this step. A filing that would drive the bond's `outstanding_liability_cents` strictly above its `limit_cents` is rejected outright with `ERR_BOND_INSUFFICIENT` (HTTP 422) — the filing fails rather than merely saturating the bond. And a filing attempted against a bond that is already in `SATURATED` status is rejected with `ERR_BOND_SATURATED` (HTTP 409). A `LicensedBroker` may instead cancel a draft entry, moving it from `DRAFT` to the terminal `CANCELLED` state and incrementing its version; cancellation is permitted only while the entry is in `DRAFT`.

### 3.5. CBP Review, Release, and the Examination Branch

Once an entry is `FILED`, a `CBPOfficer` reviews it, and the review forks. The reviewing officer must never be the user who filed the entry: if the officer's `X-User-ID` equals the entry's `filed_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The review takes an `action` of either `RELEASE` or `HOLD`.

A release advances the entry from `FILED` to `RELEASED`. It is permitted only while the entry is `FILED`, only when the officer differs from the filer, and only when every partner-government-agency review on the entry has a `decision` of `MAY_PROCEED` and the referenced ISF is in `FILED` status; on this direct `FILED`→`RELEASED` path, if the `isf_filing_id` is unset or the referenced ISF is not in `FILED` status the release is rejected with `ERR_ISF_NOT_FILED` (HTTP 409). An entry may not be released while any review on it is `PENDING` or `HOLD`, and never if any is `REFUSED`; a release attempted in those circumstances is rejected with `ERR_PGA_NOT_CLEARED` (HTTP 409). On release, the system stamps `reviewed_by_user_id` with the officer's `X-User-ID`, sets the entry `status` to `RELEASED`, and increments the entry's version. Two cascades fire: the referenced ISF transitions from `FILED` to the terminal `MATCHED` state, recording that the manifest has matched the security filing; and the entry is scheduled onto the importer's open monthly statement, as described in §3.8.

A hold advances the entry from `FILED` to `HOLD_EXAM`. It is permitted only while the entry is `FILED`, only when the reviewing officer differs from the filer, and when at least one partner-government-agency review on the entry has a `decision` of `HOLD` or `REFUSED`, or the `action` itself is explicitly `HOLD`. A hold stamps `reviewed_by_user_id`, sets the entry `status` to `HOLD_EXAM`, and increments the entry's version. Unlike a release, a hold schedules no statement and matches no ISF.

An entry under examination can be cleared and released. A `CBPOfficer` other than the filer releases a `HOLD_EXAM` entry, advancing it from `HOLD_EXAM` to `RELEASED`, permitted only while the entry is `HOLD_EXAM` and only when every partner-government-agency review on it has `decision` of `MAY_PROCEED`. This release fires the same ISF match and monthly-statement scheduling as the direct release, sets the entry `status` to `RELEASED`, increments the entry's version, and additionally transitions every `BOOKED` examination slot booked against this entry to `RELEASED_SLOT`, freeing the station.

### 3.6. Partner Government Agency Review

When a line falls under FDA or USDA jurisdiction, a **partner-government-agency review** governs whether the entry may proceed. A `LicensedBroker` or a `CBPOfficer` opens a review by supplying the `entry_id` it concerns and the `agency`, either `FDA` or `USDA`. A new review starts with a `decision` of `PENDING` and a null `reviewed_by_user_id`. Reviews may be fetched and listed, the list optionally filtered by `entry_id`.

A `CBPOfficer` records a disposition by supplying a `decision`. From `PENDING`, the review may move to `MAY_PROCEED` or to `HOLD`; either transition is permitted only while the review is `PENDING` and the entry under review is in `FILED` or `HOLD_EXAM` status, and each stamps `reviewed_by_user_id` with the officer's `X-User-ID` and increments the review's version. A `HOLD` review blocks the entry's release until it is upgraded. From `HOLD`, the review may be upgraded to `MAY_PROCEED` — a cyclic recovery permitted only while the review is `HOLD` and the entry is `FILED` or `HOLD_EXAM`, incrementing the review's version — or it may be escalated to the terminal `REFUSED` state, likewise permitted only while the review is `HOLD` and the entry is `FILED` or `HOLD_EXAM`, incrementing the review's version. Once any review on an entry is `REFUSED`, that entry can never be released. The `MAY_PROCEED` and `REFUSED` states are terminal for a review.

### 3.7. Examination Slots at the Station

While an entry is held for examination, a `CBPOfficer` books a slot at a **centralized examination station** — the physical resource whose calendar must not double-book. Booking supplies the `station_code`, either `CES_LAX` or `CES_JFK`; the `entry_id` being examined, which must be in `HOLD_EXAM` status; and the `window_start` and `window_end` instants bounding the slot. A new slot starts in `BOOKED` status. The slot's interval is treated as half-open, covering from `window_start` up to but not including `window_end`. The `window_end` must be strictly after the `window_start`, and the entry must be in `HOLD_EXAM`; a slot booked for an entry not in `HOLD_EXAM`, or with a `window_end` that is not strictly after its `window_start`, is rejected with `ERR_INVALID_EXAM_WINDOW` (HTTP 422). Slots may be fetched and listed, the list optionally filtered by `entry_id` or `station_code`.

A new slot must not overlap any `BOOKED` slot already on the same `station_code`. Because intervals are half-open, two slots overlap exactly when the first's `window_start` is strictly before the second's `window_end` and the second's `window_start` is strictly before the first's `window_end`; adjacency, where one slot's end equals the next slot's start, does not collide. An overlapping booking on the same station is rejected with `ERR_EXAM_SLOT_OVERLAP` (HTTP 409). Overlap is evaluated only against slots on the same station; different stations never conflict. A `CBPOfficer` may cancel a `BOOKED` slot, moving it from `BOOKED` to the terminal `CANCELLED_SLOT` state and incrementing its version; cancellation is permitted only while the slot is `BOOKED`, and it frees the slot's interval so a later booking on the same station and window no longer overlaps it. The remaining terminal state, `RELEASED_SLOT`, is reached only by the cascade when the examined entry is cleared and released, as described in §3.5.

### 3.8. Monthly Statements and Periodic Settlement

Released entries are billed periodically through a **monthly statement**. An `AccountAdmin` opens one by supplying the `importer_id` whose entries roll up onto it and the `period_month` in `YYYY-MM` form. A new statement starts in `OPEN` status with `statement_total_cents` and `entry_count` at 0. The `period_month` must match the `YYYY-MM` pattern; a malformed value is rejected with `ERR_INVALID_FORMAT` (HTTP 422). Statement periods are whole calendar months treated as closed intervals from the month's first day to its last day; creating a statement whose `period_month` names a calendar month that overlaps an existing open statement for the same importer — in practice, a second open statement for the same importer and month — is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409). Statements may be fetched and listed, the list optionally filtered by `importer_id`.

When an entry is released — whether directly from `FILED` or out of `HOLD_EXAM` — it is scheduled onto the open monthly statement for that importer and the calendar month of the current logical clock instant; if no such open statement exists, one is created. The entry's `statement_id` is set to that statement, and the statement's `statement_total_cents` and `entry_count` are recomputed. The `statement_total_cents` is the sum of `total_duties_owed_cents` over every entry whose `statement_id` equals this statement and whose `status` is `RELEASED` or `LIQUIDATED`; the `entry_count` is the number of entries scheduled onto the statement. These totals are reconciled both at scheduling and whenever a later liquidation or correction changes a scheduled entry's owed total.

An `AccountAdmin` settles a statement, advancing it from `OPEN` to the terminal `SETTLED` state. Settlement is permitted only while the statement is `OPEN` and only when every entry whose `statement_id` equals this statement has reached `LIQUIDATED` status; it increments the statement's version. A statement therefore settles only after all of its entries have liquidated.

### 3.9. Liquidation — Final Pricing and Cross-Aggregate Reconciliation

Liquidation is where provisional figures are replaced by final ones and the consequences cascade across the bond and the statement. A `CBPOfficer` other than the entry's filer liquidates a `RELEASED` entry, advancing it from `RELEASED` to the terminal `LIQUIDATED` state; liquidation is permitted only while the entry is `RELEASED` and only when the officer's `X-User-ID` differs from the entry's `filed_by_user_id`.

On liquidation each line's `line_duty_cents` is recomputed under the final rule, which differs from the provisional rule only in how a `USMCA` claim is treated. A line claiming `USMCA` earns its zero duty — `line_duty_cents` of 0 and `preference_verified` set to true — only when the entry's `country_of_origin` is one of the FTA-eligible origins, namely `MX` or `CA`; otherwise the full base duty is restored as `line_duty_cents` and `preference_verified` is set to false. A line with no preference takes its base duty as before. The base duty itself is computed exactly as at filing: `dutiable_value_cents` multiplied by the chapter rate in basis points (1650 for apparel chapters "61" and "62", 250 for machinery chapters "84" and "85", 500 general), divided by 10000, rounded half up.

The entry's `final_total_cents` is then assembled by the same six-step procedure as the provisional total, using the final line duties: total dutiable value as the sum of line `dutiable_value_cents`; total duty as the sum of the per-line final `line_duty_cents`; the merchandise processing fee ad valorem at 35 basis points clamped between 3215 and 62333 cents, waived to 0 only when every line's `preference_verified` is true in this final variant; the harbor maintenance fee at 13 basis points for any entry whose `entry_type` is not `FTZ_06` and 0 for `FTZ_06`; the tax at 200 basis points when any line is `FDA`-flagged under the final state and 0 otherwise; and the grand total as the sum of those four components.

Liquidation sets `total_duties_owed_cents` equal to `final_total_cents`, computes the delta as the final total minus the provisional total, sets the entry `status` to `LIQUIDATED`, and increments the entry's version. The bond's `outstanding_liability_cents` is then increased by that delta — which may be negative when the final figure is lower than the provisional one — and if this reconciliation drops the bond's outstanding liability strictly below its `limit_cents`, a `SATURATED` bond auto-transitions back to `ACTIVE`. Finally, the monthly statement the entry sits on has its `statement_total_cents` recomputed to reflect the entry's new owed total.

### 3.10. Post-Summary Corrections and Protests

After an entry is liquidated, its fiscal state may be reopened by a **post-summary correction** or a formal **protest**. An `ImporterUser` or a `LicensedBroker` submits one by supplying the `entry_id` of the liquidated entry, a `filing_kind` of either `PSC` or `PROTEST`, the signed `corrected_value_delta_cents` representing the change to total dutiable value the filer claims (which may be negative for a refund claim), and the `expected_entry_version` carrying the entry's `version` as the filer last observed it. A new filing starts in `SUBMITTED` status with `adjustment_cents` of 0. As described in §2.7, the submission is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412) if `expected_entry_version` does not match the entry's current `version`. Filings may be fetched and listed, the list optionally filtered by `entry_id`.

A `CBPOfficer` adjudicates the filing. Granting it advances it from `SUBMITTED` to the terminal `GRANTED` state; this is permitted only while the filing is `SUBMITTED` and the referenced entry is `LIQUIDATED`. On grant, the system computes the `adjustment_cents`, a signed duty adjustment derived from the claimed value change. If every line of the entry has `preference_verified` true, the value change is duty-free under USMCA and the `adjustment_cents` is 0. Otherwise the `adjustment_cents` is the `corrected_value_delta_cents` multiplied by the general rate of 500 basis points, divided by 10000, rounded half up, with the sign preserved so that a negative delta yields a refund; for a negative delta the rounding is applied to the magnitude and the sign is then restored — that is, the half-up step rounds the absolute value away from zero and the result is negated — so the rounding is symmetric about zero rather than biased toward positive infinity. Corrections and protests share this one formula; only the `filing_kind` label distinguishes them. The grant then adds the `adjustment_cents` to the entry's `final_total_cents` and sets the entry's `total_duties_owed_cents` to that new final total; increases the bond's `outstanding_liability_cents` by the `adjustment_cents`, which may auto-transition the bond either way between `ACTIVE` and `SATURATED`; recomputes the monthly statement's `statement_total_cents`; sets the filing `status` to `GRANTED`; and increments the filing's version. The conserved invariant is that after the cascade the bond's `outstanding_liability_cents` equals the sum of its secured entries' owed totals.

Denying a filing advances it from `SUBMITTED` to the terminal `DENIED` state, permitted only while the filing is `SUBMITTED` and the referenced entry is `LIQUIDATED`. A denial sets the filing's `adjustment_cents` to 0, has no fiscal effect on the entry, bond, or statement, sets the filing `status` to `DENIED`, and increments the filing's version.

### 3.11. The Logical Clock

An `AccountAdmin` may advance the server's logical clock by supplying the target instant as `to_iso8601`. The clock starts, at server startup, at exactly `2026-01-01T00:00:00Z`; before any such call is made the clock reads precisely this default and never falls back to wall-clock time. The clock governs the moment stamped as an ISF's `filed_at`, the comparison that decides `late_filing`, and the calendar month an entry is billed into when it is scheduled onto a monthly statement, so advancing it deterministically drives the advance-filing cutoff and statement-period logic.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; all other successful mutations and reads return HTTP 200. Request bodies, response shapes, and side effects are not repeated here — they are specified in the §3 workflow narratives. The table below lists method, path, a short description, and the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/importers` | Create an importer of record. | `AccountAdmin` |
| GET | `/importers/{id}` | Fetch an importer. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/importers` | List importers, optionally filtered by owner or active continuous bond. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/bonds` | Create a bond securing an importer (starts PENDING). | `AccountAdmin` |
| GET | `/bonds/{id}` | Fetch a bond. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/bonds` | List bonds, optionally filtered by importer. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/bonds/{id}/activate` | Activate a PENDING bond. | `AccountAdmin` |
| POST | `/bonds/{id}/terminate` | Terminate an ACTIVE bond with zero outstanding liability. | `AccountAdmin` |
| POST | `/isf-filings` | Create an ISF (10+2) filing in DRAFT. | `LicensedBroker`, `ImporterUser` |
| GET | `/isf-filings/{id}` | Fetch an ISF filing. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/isf-filings` | List ISF filings, optionally filtered by importer. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/isf-filings/{id}/file` | Transition an ISF DRAFT→FILED (requires all 10 data elements). | `LicensedBroker` |
| POST | `/isf-filings/{id}/cancel` | Cancel a DRAFT ISF. | `LicensedBroker` |
| POST | `/entries` | Create a customs entry (7501) in DRAFT. | `LicensedBroker`, `ImporterUser` |
| GET | `/entries/{id}` | Fetch an entry. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/entries` | List entries, optionally filtered by importer, bond, isf, or statement. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/entries/{id}/lines` | Add an HTS line to a DRAFT entry. | `LicensedBroker`, `ImporterUser` |
| GET | `/entries/{id}/lines` | List the HTS lines of an entry. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/entries/{id}/file` | File the entry (DRAFT→FILED); computes provisional charges and reconciles the bond. | `LicensedBroker` |
| POST | `/entries/{id}/review` | CBP review of a FILED/HOLD_EXAM entry; action RELEASE or HOLD. | `CBPOfficer` |
| POST | `/entries/{id}/liquidate` | Liquidate a RELEASED entry; computes final charges and reconciles bond + statement. | `CBPOfficer` |
| POST | `/entries/{id}/cancel` | Cancel a DRAFT entry. | `LicensedBroker` |
| POST | `/pga-reviews` | Open a PGA (FDA/USDA) review on an entry. | `LicensedBroker`, `CBPOfficer` |
| GET | `/pga-reviews/{id}` | Fetch a PGA review. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/pga-reviews` | List PGA reviews, optionally filtered by entry. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/pga-reviews/{id}/decide` | Record a PGA disposition (MAY_PROCEED / HOLD / REFUSED). | `CBPOfficer` |
| POST | `/exam-slots` | Book a centralized examination station slot for a HOLD_EXAM entry. | `CBPOfficer` |
| GET | `/exam-slots/{id}` | Fetch an exam slot. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/exam-slots` | List exam slots, optionally filtered by entry or station. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/exam-slots/{id}/cancel` | Cancel a BOOKED exam slot, freeing its interval. | `CBPOfficer` |
| POST | `/monthly-statements` | Create an OPEN monthly statement for an importer/period. | `AccountAdmin` |
| GET | `/monthly-statements/{id}` | Fetch a monthly statement. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/monthly-statements` | List monthly statements, optionally filtered by importer. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/monthly-statements/{id}/settle` | Settle an OPEN statement once all its entries are LIQUIDATED. | `AccountAdmin` |
| POST | `/post-summary-corrections` | Submit a post-summary correction or protest against a LIQUIDATED entry. | `LicensedBroker`, `ImporterUser` |
| GET | `/post-summary-corrections/{id}` | Fetch a PSC/protest. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| GET | `/post-summary-corrections` | List PSCs/protests, optionally filtered by entry. | `AccountAdmin`, `ImporterUser`, `LicensedBroker`, `CBPOfficer` |
| POST | `/post-summary-corrections/{id}/grant` | Grant a PSC/protest; applies the duty adjustment and reconciles bond + statement. | `CBPOfficer` |
| POST | `/post-summary-corrections/{id}/deny` | Deny a PSC/protest (no fiscal effect). | `CBPOfficer` |
| POST | `/_clock/set_current_utc` | Set the server logical clock. | `AccountAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_BOND_IMPORTER_MISMATCH` | 422 |
| `ERR_PGA_NOT_CLEARED` | 409 |
| `ERR_ISF_NOT_FILED` | 409 |
| `ERR_ISF_INCOMPLETE` | 422 |
| `ERR_ENTRY_PRECEDES_MANIFEST` | 422 |
| `ERR_INVALID_FORMAT` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_BOND_INSUFFICIENT` | 422 |
| `ERR_BOND_SATURATED` | 409 |
| `ERR_STALE_ENTRY_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
| `ERR_NO_LINES` | 422 |
| `ERR_INVALID_EXAM_WINDOW` | 422 |
| `ERR_EXAM_SLOT_OVERLAP` | 409 |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 |
