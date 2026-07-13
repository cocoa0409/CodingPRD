# Ad Agency Ops API — Product Requirements Document

## 1. Introduction

A full-service marketing agency lives or dies on the gap between what it promises a client and what it can prove it delivered. Today that gap is filled with spreadsheets: one workbook tracks the prepaid retainer, another tracks who signed which statement of work and at what hourly rate, a third tracks creative revision rounds, and a fourth — usually maintained by a single overworked finance analyst — tries to reconcile media commitments against publisher invoices before the month closes. When a client's prepaid balance runs dry mid-month, nobody finds out until an invoice bounces, and by then three campaign teams have already burned another fortnight of unbillable hours.

This document specifies the Ad Agency Ops API: a single backend of record for the commercial spine of the agency. It covers the advertiser relationship (clients, prepaid retainers, statements of work and their pinned rate cards), the delivery layer (campaign briefs, creative deliverables and their approval loop, logged time and vendor pass-through costs), the media layer (budgeted media plans, insertion orders against publisher inventory, and post-flight delivery figures), and the money layer (invoice assembly under two competing billing modes, retainer drawdown, voids, and cash payments). Two things make this system harder than a CRUD store. First, money moves through a chain of consequences — issuing one invoice can drain a retainer, freeze an advertiser's credit, and halt every one of that advertiser's live campaigns in a single request. Second, every number the agency bills must be reproducible: rates are frozen at signature, creative versions are frozen at approval, and the rounding order in every formula is part of the contract, not an implementation detail.

The service is intended for the agency's own staff and for a client-side approver who logs in to sign, review and pay. Every write is auditable, every cascade is compensated by an exact inverse, and two ledgers — the retainer's cash and the media plan's budget — are held to conservation invariants that must never drift.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same rejection applies when `X-User-Role` carries a value that is not one of the five roles this system recognises: `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, and `ClientReviewer`. Once the caller is authenticated, the role is checked against the set of roles authorised for the endpoint being called (see the table in section 4); a caller whose role is not in that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles differ in how `X-User-ID` is interpreted:

- When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for its own purposes but never compares it to any entity's `id`. `AgencyAdmin` is the agency's operations and finance function: it owns the reference data (advertisers, rate cards, staff, publisher inventory), the cash (retainers, invoice issue and void), and the logical clock.
- When `X-User-Role` is `AccountManager`, `X-User-ID` is the `id` of the acting `StaffMember`. The `AccountManager` is the client-facing agency lead: they draft statements of work and campaigns, take campaigns live, approve other people's time, record and approve vendor costs, and assemble invoices.
- When `X-User-Role` is `CreativeLead`, `X-User-ID` is the `id` of the acting `StaffMember`. The `CreativeLead` opens creative deliverables and submits asset cuts for client review.
- When `X-User-Role` is `MediaBuyer`, `X-User-ID` is the `id` of the acting `StaffMember`. The `MediaBuyer` owns media plans and the entire insertion-order lifecycle.
- When `X-User-Role` is `ClientReviewer`, `X-User-ID` is the `id` of the acting `Client` — that is, of the advertiser itself. Ownership checks on any resource that references a `Client` compare that resource's client foreign key to `X-User-ID`.

Ownership is enforced wherever an entity-backed caller acts on a resource. For a `ClientReviewer`, `X-User-ID` must equal the advertiser the target resource resolves to: the `client_id` of a statement of work being countersigned, the `client_id` of an invoice being paid, and — for a media plan being signed off or a deliverable being reviewed — the `client_id` of the campaign that owns it. For the three staff roles, logging time requires that `X-User-ID` equal the `staff_id` named in the request body: nobody may log another person's hours. A violation of any of these ownership rules is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

One further access rule is structural rather than positional. The agency operates a segregation of duties between the person who records work and the person who signs off on it: an `AccountManager` approving a time entry must not be the same `StaffMember` who logged it. Self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every collection-listing endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and is a zero-based index into the result set. A value outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List results are always returned in ascending `created_at` order — the oldest resource first — so that paging through a collection is stable; where two rows carry an identical `created_at`, the order in which they were created breaks the tie. On every list response the `meta` object carries `limit`, `offset`, `total_count` (the number of rows matching the filters before pagination is applied) and `has_more` (true when rows remain beyond the current window). Filters offered by individual list endpoints, described in section 3 alongside the resources they narrow, are applied before pagination.

### 2.4. Resource Identity, Timestamps and Versioning

Every persisted resource carries four common properties. `id` is a server-minted UUID with no type prefix; clients never supply it. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that starts at 1 when the resource is created. Every mutation of a resource — whether triggered directly by the caller or indirectly as the consequence of some other operation elsewhere in the system — refreshes that resource's `updated_at` and increments its `version` by exactly 1. That increment is counted once per request, not once per write: a resource that a single request touches more than once — because the caller wrote it directly *and* a cascade hop of the same request wrote it again, or because several hops of one cascade chain land on it — still moves exactly one `version` and takes a single `updated_at` refresh. Datetime values supplied by the caller (a retainer's or an invoice's period bounds, a SOW's effective window, a time entry's worked instants, a vendor cost's `incurred_on`, an insertion order's flight dates) are stored and echoed back byte for byte as the caller wrote them; only the server-minted `created_at`, `updated_at` and `api_request_timestamp` are normalised to the three-fractional-digit form. All thirteen resource types in this system — advertisers, rate cards, staff members, media placements, retainers, statements of work, campaigns, deliverables, time entries, vendor costs, media plans, insertion orders and invoices — carry all four properties; there are no exceptions.

`version` matters beyond bookkeeping. It is the coordination token that the stale-version guards in section 2.7 compare against, and it is the value that a statement of work freezes when it pins a rate card. Because cascades increment the `version` of every resource they touch, a `version` observed before a cascade fired is exactly the signal the API needs to detect a client acting on an out-of-date view.

### 2.5. The Logical Clock

The service does not read the host's wall clock. It keeps a logical clock which, before any caller has moved it, reads exactly `2026-05-01T00:00:00Z`, and which never falls back to real time. An agency operator may advance or reset the clock by supplying a `to_iso8601` instant; the call answers with the resulting `now_utc` — rendered as an ISO 8601 UTC instant with three fractional digits — and with `expired_sow_ids`, the list of statement-of-work identifiers that this particular move retired, in ascending `created_at` order. Only that move's retirements are listed: a SOW retired by an earlier clock call does not reappear. The move is not required to go forward, but expiry is a one-way door — winding the clock back to an instant before an already-`EXPIRED` SOW's `effective_end` does not return it to `COUNTERSIGNED`. Every date and datetime comparison in this document — SOW expiry, retainer periods, invoice billing windows, flight dates — is evaluated against this logical clock, not against real time.

### 2.6. Money, Minutes and Rounding Discipline

All monetary amounts in this system are integers denominated in cents. There are no floating-point currency values anywhere in a request or a response. Wherever a formula produces a fractional cent, the result is rounded half up to the nearest whole cent — a value of exactly one half cent rounds away from zero, upward. Percentages that are reported back to the caller (utilization figures and gross margin) are rounded half up to one decimal place; percentages that are *inputs* (a statement of work's markup, an invoice's discount rate) are plain decimal fractions where 0.175 means 17.5 percent.

Two rounding rules are part of the contract and are not interchangeable with mathematically similar alternatives:

- **Round per line, then sum.** Where a marked-up total is assembled from several supplier lines, each line is marked up and rounded to a whole cent on its own, and only then are the rounded lines added together. Marking up the summed base and rounding once at the end produces a different, incorrect answer.
- **Round per leg, then sum.** Where a time entry's chargeable value is split into a regular leg and an overtime leg, each leg is converted to cents and rounded to a whole cent independently, and the two rounded legs are then added.

Minutes are whole minutes. The duration of a worked interval is the whole number of minutes between its start and its end, with any residual seconds discarded — the elapsed seconds are divided by 60 and truncated downward, so a 90-second interval is 1 minute and a 59-second interval is 0 minutes.

### 2.7. Stale-Version Guards (Optimistic Concurrency Control)

Two write operations in this system commit a scarce resource that the caller can only have sized correctly by reading a parent resource first. Both are protected by an optimistic-concurrency guard: the request must carry the parent's `version` as the caller last observed it, and the write is refused if the parent has moved on since.

The first guard sits on insertion-order creation. The request must carry `expected_media_plan_version`, holding the `version` of the target `MediaPlan` as the client last read it. If that value does not equal the plan's current `version`, the create is rejected with `ERR_STALE_MEDIA_PLAN_VERSION` (HTTP 412) and no budget is committed. Without this guard nothing in the state machine would stop a buyer from committing budget against an out-of-date view of the plan's uncommitted funds, because reserving a second, different placement is a perfectly legitimate operation on its own.

The second guard sits on invoice issue. The request must carry `expected_retainer_version`, holding the `version` of the `Retainer` that the invoice draws down, as the client last read it. If that value does not equal the retainer's current `version`, the issue is rejected with `ERR_STALE_RETAINER_VERSION` (HTTP 412) and no cash moves. Issuing a second, different invoice against the same retainer is likewise legitimate, so only the stale-version check prevents a writer holding an outdated balance from over-drawing it.

No other endpoint takes a version field. Reading the parent resource — the media plan for the first guard, the retainer for the second — is the canonical way to obtain a fresh value.

### 2.8. Validation Order and Path Resolution

When a single request violates more than one rule, the response must report the violation that comes first in the following ordering. This ordering is normative; a lower-numbered check that fails masks every higher-numbered one.

1. Both `X-User-ID` and `X-User-Role` are present and non-empty — otherwise `ERR_UNAUTHENTICATED`.
2. `X-User-Role` names one of the five recognised roles — otherwise `ERR_UNAUTHENTICATED`.
3. The caller's role is authorised for this endpoint — otherwise `ERR_FORBIDDEN_ROLE`.
4. The request body is well formed: every required field is present, every enum value is a member of its declared set, every integer is an integer inside its declared range, every date and datetime parses, a media plan's channel whitelist is a non-empty array, a time entry's end instant is strictly after its start instant and falls on the same UTC calendar date, an insertion order's flight end is on or after its flight start, and every period end is strictly after its period start — otherwise `ERR_INVALID_REQUEST`. This check runs on every write endpoint.
5. Every identifier embedded in the URL path resolves to a live resource, checked left to right — otherwise the matching not-found error for the entity that failed (`ERR_CLIENT_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND`, `ERR_SOW_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`, `ERR_VENDOR_COST_NOT_FOUND`, `ERR_MEDIA_PLAN_NOT_FOUND`, `ERR_INSERTION_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`), all HTTP 404. On a read endpoint, which has no body to check under rule 4, this path resolution runs *before* any query parameter is validated: a bad `limit` or a missing report window on a path whose identifier does not resolve reports the 404, not `ERR_INVALID_REQUEST`.
6. Every foreign key carried in the request body resolves, checked in the order the fields are listed for that endpoint — otherwise the matching not-found error, including `ERR_MEDIA_PLACEMENT_NOT_FOUND` when an insertion order names a publisher slot that does not exist. Invoice creation, for example, resolves `client_id` first, then `campaign_id`, then `retainer_id`, and reports the first one that fails. This check applies to the creation of retainers, statements of work, campaigns, deliverables, time entries, vendor costs, media plans, insertion orders and invoices.
7. Ownership, as described in section 2.1 — otherwise `ERR_NOT_RESOURCE_OWNER`. This guards SOW countersign, media-plan approval, deliverable request-changes, deliverable approval, invoice payment, and time-entry creation.
8. Segregation of duties on time-entry approval — otherwise `ERR_SEGREGATION_OF_DUTIES`.
9. The stale-version guards of section 2.7, on insertion-order creation and invoice issue — otherwise `ERR_STALE_MEDIA_PLAN_VERSION` or `ERR_STALE_RETAINER_VERSION`, both HTTP 412.
10. The target entity is in a state from which the requested transition is legal — otherwise `ERR_INVALID_STATE` (HTTP 409). This applies to every action endpoint: approving an already-`APPROVED` deliverable, issuing an already-`ISSUED` invoice, placing a `CANCELLED` insertion order, paying an invoice that is still `DRAFT`, and voiding an invoice against which cash has already been received all land here.
11. The cross-entity state gate on the owning campaign: the campaign must be `IN_FLIGHT`. A campaign in `ON_HOLD` rejects with `ERR_CAMPAIGN_ON_HOLD` (HTTP 409); a campaign in any other non-`IN_FLIGHT` state rejects with `ERR_INVALID_STATE`. This gate guards nine operations: time-entry creation, time-entry approval, vendor-cost creation, vendor-cost approval, deliverable submit, deliverable request-changes, deliverable approval, media-plan approval, and campaign launch — where, at launch, it is the owning advertiser being in `CREDIT_HOLD` that raises `ERR_CAMPAIGN_ON_HOLD`.
12. The cross-entity state gate on the governing statement of work: it must be `COUNTERSIGNED`. A `DRAFT` SOW rejects with `ERR_SOW_NOT_COUNTERSIGNED` (HTTP 409) and an `EXPIRED` SOW rejects with `ERR_SOW_EXPIRED` (HTTP 409). This gate guards two operations: time-entry creation and campaign launch.
13. The cross-entity state gate on the governing media plan: sending an insertion order to the publisher requires the plan to be `APPROVED` — otherwise `ERR_MEDIA_PLAN_NOT_APPROVED` (HTTP 409).
14. Referential eligibility: the publisher slot's channel must be whitelisted on the media plan, otherwise `ERR_PLACEMENT_NOT_ELIGIBLE` (HTTP 422); a campaign's statement of work must belong to the same advertiser as the campaign, and an invoice's campaign and retainer must both belong to the same advertiser as the invoice, otherwise `ERR_INVALID_REQUEST` (HTTP 400). This check guards insertion-order creation, campaign creation and invoice creation.
15. Interval-occupancy conflicts on insertion-order creation (`ERR_PLACEMENT_FLIGHT_CONFLICT`) and time-entry creation (`ERR_TIME_ENTRY_OVERLAP`), both HTTP 409, as specified in sections 3.5 and 3.7.
16. Cardinality and round limits: the revision cap on deliverable request-changes (`ERR_REVISION_LIMIT_EXCEEDED`) and the empty-invoice check on invoice creation (`ERR_INVOICE_NO_LINES`), both HTTP 422.
17. Capacity and budget ceilings, evaluated last of all: the daily minute cap and the labor cap on time-entry creation (`ERR_DAILY_MINUTES_EXCEEDED`, `ERR_SOW_LABOR_CAP_EXCEEDED`), the media budget ceiling on insertion-order creation (`ERR_MEDIA_BUDGET_EXCEEDED`), and the overpayment check on invoice payment (`ERR_PAYMENT_EXCEEDS_BALANCE`), all HTTP 422.

### 2.9. Cascades, Compensating Actions and Conservation Invariants

A defining characteristic of this system is that a single write can propagate through several resources. Cascades are not optional side channels — they are part of the request that triggered them, they complete before the response is returned, and every resource they touch has its `version` incremented and its `updated_at` refreshed exactly as if it had been written directly.

Every cascade in this system has an exact inverse. Draining a retainer to zero puts the advertiser on credit hold and freezes its live campaigns; funding the retainer again, or voiding the invoice that drained it, un-freezes them. Reserving publisher inventory commits budget out of a media plan; cancelling the order releases exactly that amount back. Issuing a final invoice marks its lines as billed; voiding that invoice returns them to their approved state so they may be billed again. The API is expected to hold two conservation invariants at all times:

- **Retainer cash.** A retainer's `funded_cents` always equals its `balance_cents` plus the sum of `retainer_applied_cents` across every invoice drawing on that retainer whose approval dimension is `ISSUED`. Void moves an invoice out of that filter and simultaneously returns its applied cash to the balance, so the identity holds with zero drift. Note that voiding does **not** zero the invoice's own `retainer_applied_cents` — the invoice keeps its historical record, and it is the approval-status filter that excludes it.
- **Media budget.** A media plan's `approved_budget_cents` always equals its `uncommitted_cents` plus the sum of `gross_cents` across every insertion order on that plan whose status is `RESERVED`, `PLACED` or `DELIVERED`. Cancelled orders hold no budget; delivered orders still do.

## 3. Business Logic & Workflows

### 3.1. Reference Data and the Advertiser's Prepaid Balance

Everything begins with the advertiser. Registering one records its legal `name` (non-empty, at most 120 characters), its `industry` — one of `RETAIL`, `FINANCE`, `CPG`, `TECH` or `AUTO`, used only for reporting segmentation — and a non-empty `billing_email` for the accounts-payable contact. A newly registered advertiser has `status` `ACTIVE`. That field is never set by a caller: it flips to `CREDIT_HOLD` only as a consequence of the retainer ledger described below, and back to `ACTIVE` only when the retainers recover.

Alongside advertisers, the agency maintains three other reference collections. A **rate card** is a published price list with a human `name` such as "Standard 2026" and three live hourly rates in cents, each a non-negative integer: `rate_junior_cents_per_hour`, `rate_senior_cents_per_hour` and `rate_director_cents_per_hour`. Rate cards are editable — any of the three rate columns may be revised in place, each of them optional in the edit payload, and each revision bumps the card's `version`, including an edit that names no column at all or restates a column with the value it already holds — but section 3.2 explains why revising a card never re-prices work already contracted against it. The card's `name` is not editable. A **staff member** has a `full_name`, a billing `grade` of `JUNIOR`, `SENIOR` or `DIRECTOR` (which selects the matching rate column), a `standard_daily_capacity_minutes` figure that defaults to the standard eight-hour day of 480 minutes and must lie between 1 and 1440, and a `cost_rate_cents_per_hour` giving the agency's internal, unbilled cost of that person per hour as a non-negative integer. A **media placement** is a slot of publisher inventory, described by the `publisher_name` that owns it, its `channel` — one of `DISPLAY`, `VIDEO`, `SOCIAL`, `OOH` or `PRINT` — and a `min_dark_days` figure between 0 and 30 (defaulting to 0) that records how many unsold days the publisher insists on between two consecutive flights on that slot.

The **retainer** is where the advertiser's cash lives. Opening one names the `client_id` it belongs to, an `initial_funding_cents` amount, and the half-open period it covers: `period_start` is the inclusive first date and `period_end` the exclusive last date, which must fall strictly after `period_start`. At creation both `funded_cents` and `balance_cents` are set to the initial funding amount (a non-negative integer), and `status` is `ACTIVE` — unconditionally, so a retainer opened with an `initial_funding_cents` of 0 is still born `ACTIVE` and leaves its advertiser untouched; the mechanical status rule below engages only once a later write actually moves the balance. `funded_cents` records all cash ever placed on the retainer and never decreases; `balance_cents` records the cash still unconsumed. Topping the retainer up adds the supplied `amount_cents` — an integer of at least 1 — to both figures, and is legal from either status.

The retainer's `status` follows its balance mechanically: `ACTIVE` for as long as `balance_cents` is greater than zero, and `DEPLETED` at the instant `balance_cents` reaches exactly zero. It returns to `ACTIVE` the instant the balance becomes greater than zero again, which can happen either through a top-up or through the void of an invoice that had drawn it down. When a retainer moves `ACTIVE → DEPLETED`, the owning advertiser is put on credit hold — `ACTIVE → CREDIT_HOLD` — and, in turn, every campaign of that advertiser then `IN_FLIGHT` is frozen `IN_FLIGHT → ON_HOLD`. The reverse chain runs on recovery: when a retainer moves `DEPLETED → ACTIVE`, the advertiser returns `CREDIT_HOLD → ACTIVE` provided that *every* retainer of that advertiser is now `ACTIVE`, and every campaign of that advertiser sitting in `ON_HOLD` is released back to `IN_FLIGHT`. Each hop of that chain increments the `version` of the resource it moves.

Retainers may be listed and filtered by `client_id` and by `status`, and an individual retainer may be read directly — which is how a caller obtains the `version` the invoice-issue guard demands.

### 3.2. Statements of Work and the Rate Pin

A statement of work binds a `client_id` to a body of contracted labour. Drafting one records a non-empty `title`, the `rate_card_id` whose prices it references, a `labor_cap_cents` ceiling (a non-negative integer) on cumulative estimated labour bookable against it, a `markup_pct` between 0 and 1 expressing the pass-through markup applied to every supplier cost billed under it (0.175 meaning 17.5 percent), and the half-open coverage window `effective_start` (inclusive) to `effective_end` (exclusive, and strictly after the start). A new SOW has `status` `DRAFT`, a `consumed_labor_cents` of 0, and all four of its pinned columns — `pinned_rate_card_version`, `pinned_rate_junior_cents_per_hour`, `pinned_rate_senior_cents_per_hour` and `pinned_rate_director_cents_per_hour` — set to null.

Countersigning is the client's act, performed by the `ClientReviewer` whose `X-User-ID` is the advertiser the SOW names, and it is legal only from `DRAFT` and only while the logical clock still reads earlier than the SOW's `effective_end`; a countersign attempted at or after that instant is rejected with `ERR_SOW_EXPIRED`. Countersigning moves the SOW `DRAFT → COUNTERSIGNED` and, in the same breath, **freezes the price list**: the rate card's `version` is copied into `pinned_rate_card_version` and its three live rate columns are copied into the three pinned rate columns. From that moment the SOW bills at the frozen rates for the rest of its life. An agency operator may revise the rate card afterwards as often as they like; not one cent of that revision reaches a SOW that has already been countersigned.

A statement of work retires by clock, not by request. When the logical clock is moved to or past a `COUNTERSIGNED` SOW's `effective_end`, that SOW transitions `COUNTERSIGNED → EXPIRED` and its identifier appears in the clock call's `expired_sow_ids`. Expiry does not cascade to campaigns — a campaign under an expired SOW stays exactly where it was — but no further time may be logged against it: such an attempt is rejected with `ERR_SOW_EXPIRED`. Statements of work may be listed and filtered by `client_id`, by the `rate_card_id` they reference, and by `status`; reading one returns its pinned snapshot and its running `consumed_labor_cents`.

### 3.3. Campaigns: The Brief, the Launch, and the Hold

A campaign is created by an `AccountManager` under exactly one statement of work. The payload carries the `client_id` of the advertiser, the `sow_id` of the funding SOW — whose own `client_id` must equal the campaign's, or the request is rejected as malformed — a non-empty `name`, the `brief_summary` (non-empty, at most 2000 characters) that constitutes the creative brief, and an `objective` of `AWARENESS`, `CONSIDERATION` or `CONVERSION`. Campaigns start in `DRAFT`.

Taking a campaign live is the `AccountManager`'s call, and it moves the campaign `DRAFT → IN_FLIGHT`. Three preconditions apply beyond the campaign itself already being `DRAFT`: the `brief_summary` must be non-empty, the governing SOW must be `COUNTERSIGNED` (a `DRAFT` SOW raises `ERR_SOW_NOT_COUNTERSIGNED` and an `EXPIRED` one raises `ERR_SOW_EXPIRED`), and the owning advertiser must be `ACTIVE` — an advertiser sitting in `CREDIT_HOLD` raises `ERR_CAMPAIGN_ON_HOLD`.

`IN_FLIGHT` is the only state in which delivery work may happen. The campaign leaves it in one of two directions. It is frozen `IN_FLIGHT → ON_HOLD` purely as a consequence of its advertiser going on credit hold, and released `ON_HOLD → IN_FLIGHT` when the advertiser recovers; while frozen it rejects time entries, vendor costs, vendor-cost approvals, time-entry approvals, deliverable submissions, deliverable reviews and media-plan sign-off, all with `ERR_CAMPAIGN_ON_HOLD`. Alternatively it advances `IN_FLIGHT → WRAP_UP` when creative signs off entirely (section 3.4), and finally `WRAP_UP → CLOSED` when an issued invoice for that campaign is paid in full (section 3.8). `CLOSED` is terminal. Campaigns may be listed and filtered by `client_id`, by `sow_id`, and by `status`, and reverse-lookup reads return a campaign's deliverables or its vendor costs, each of which may itself be narrowed by `status`.

### 3.4. The Creative Review Loop and Wrap-Up

Deliverables are the creative artefacts of a campaign. A `CreativeLead` opens one against a `campaign_id` with a non-empty `title` — "Hero film 30s cut", say. A new deliverable sits in `DRAFT` with `current_asset_version` 0, `revision_round` 0, `approved_asset_version` null and `last_feedback` null.

Submitting an asset cut for review moves the deliverable to `SUBMITTED` and adds exactly 1 to `current_asset_version`. Submission is legal from two places: from `DRAFT`, for the first cut, and from `CHANGES_REQUESTED`, which is the return edge of the revision loop. Both edges require the owning campaign to be `IN_FLIGHT`.

The advertiser's `ClientReviewer` then does one of two things, and in both cases `X-User-ID` must equal the `client_id` of the campaign that owns the deliverable. Requesting changes bounces the cut back: it moves the deliverable `SUBMITTED → CHANGES_REQUESTED`, adds exactly 1 to `revision_round`, and stores the supplied `feedback` string in `last_feedback`. The loop is not infinite — the agency contracts for a maximum of three revision rounds, so a request for changes on a deliverable whose `revision_round` has already reached 3 is rejected with `ERR_REVISION_LIMIT_EXCEEDED`.

Approving is the other branch, and it is where the campaign's endgame begins. Approval is legal only from `SUBMITTED` and only while the owning campaign is `IN_FLIGHT` (a campaign in `ON_HOLD` raises `ERR_CAMPAIGN_ON_HOLD`). It moves the deliverable `SUBMITTED → APPROVED` — a terminal state — and freezes `approved_asset_version` to whatever `current_asset_version` reads at that moment, so the agency can always prove which cut the client actually signed. Approval then triggers a three-hop cascade. First, if the campaign has at least one deliverable and every one of them is now `APPROVED`, the campaign advances `IN_FLIGHT → WRAP_UP`. Second, caused by that, every media plan of that campaign sitting in `APPROVED` moves `APPROVED → LOCKED`. Third, caused by *that*, every insertion order on each newly locked plan whose status is `RESERVED` moves `RESERVED → CANCELLED`, and its `gross_cents` is released back into the plan's `uncommitted_cents`. The cascade is deliberately conditional at the third hop: orders already `PLACED` or `DELIVERED` are real commitments to a publisher and are left untouched. Every resource each hop moves — deliverable, campaign, plan, order — has its `version` incremented.

### 3.5. Time Capture, Approval, and Overtime

Logging time is the one write that any of the three staff roles may perform, and each of them may log only their own hours: the `staff_id` in the payload must equal the caller's `X-User-ID`. The payload also names the `campaign_id` the work was done for, the `started_at` instant (inclusive) and the `ended_at` instant (exclusive), and an optional `billable` flag which defaults to true. The interval must be well formed — `ended_at` strictly after `started_at`, and both on the same UTC calendar date — and the campaign must be `IN_FLIGHT` under a `COUNTERSIGNED` SOW.

From the interval the server derives two fields at creation. `work_date` is the UTC calendar date of `started_at` in `YYYY-MM-DD` form, and it is the bucket key for both the daily cap and the overtime threshold. `minutes` is the whole number of minutes between the two instants, and must be at least 1 — an interval shorter than a whole minute is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Pricing at creation is deliberately conservative. If `billable` is false, both `pinned_rate_cents_per_hour` and `estimated_amount_cents` are 0. Otherwise the server reaches through the campaign to its statement of work, selects the pinned rate column matching the staff member's `grade` — the pinned junior rate for `JUNIOR`, the pinned senior rate for `SENIOR`, the pinned director rate for `DIRECTOR` — and copies it into `pinned_rate_cents_per_hour`. The live rate card is never consulted. `estimated_amount_cents` is then the entry's minutes multiplied by that pinned hourly rate, divided by 60, rounded half up to a whole cent. This is a straight-line figure: it carries **no** overtime uplift, which is decided only at approval. Independently of the `billable` flag, `internal_cost_cents` is computed for every entry as the entry's minutes multiplied by the staff member's `cost_rate_cents_per_hour`, divided by 60, rounded half up to a whole cent; it feeds the profitability report and is never billed to anyone.

Three ceilings guard creation. A person's own diary must be consistent: the new half-open interval from `started_at` up to but not including `ended_at` must not overlap any other time entry of the same `staff_id` whose status is `SUBMITTED`, `APPROVED` or `BILLED`. Two intervals collide when the new entry starts strictly before the existing entry ends and the existing entry starts strictly before the new entry ends; entries that merely touch — where one starts at the exact instant the other ends — do not collide. A collision is rejected with `ERR_TIME_ENTRY_OVERLAP`. Next, no one may log more than ten hours in a single UTC day: the sum of `minutes` across every entry of that `staff_id` on that `work_date` whose status is `SUBMITTED`, `APPROVED` or `BILLED`, plus the new entry's minutes, must not exceed 600 minutes. Non-billable entries count toward this ceiling. Exactly 600 minutes is accepted; 601 is rejected with `ERR_DAILY_MINUTES_EXCEEDED`. Finally, the statement of work's labour budget must hold: the SOW's `consumed_labor_cents` before this request, plus the new entry's `estimated_amount_cents`, must not exceed `labor_cap_cents`. A sum exactly equal to the cap is accepted; anything strictly greater is rejected with `ERR_SOW_LABOR_CAP_EXCEEDED`.

When the entry is accepted, it is stored with status `SUBMITTED`, `approved_by_staff_id` null, and `regular_minutes`, `overtime_minutes` and `billable_amount_cents` all 0. The owning SOW's `consumed_labor_cents` is then recomputed as the sum of `estimated_amount_cents` over every time entry whose campaign belongs to that SOW and whose status is `SUBMITTED`, `APPROVED` or `BILLED` — which, since those are the only three statuses a time entry can hold, means every entry under that SOW. That recompute counts as a mutation of the SOW — bumping its `version` and its `updated_at` — only when the recomputed figure actually differs from the one already stored, so a non-billable entry, which contributes an `estimated_amount_cents` of 0, leaves the SOW's `version` where it was.

**Approval is where overtime is priced.** An `AccountManager` approves an entry that is `SUBMITTED`, on a campaign that is `IN_FLIGHT`, and — per the segregation-of-duties rule — one that they did not log themselves. Approval moves the entry `SUBMITTED → APPROVED`, stamps the approver's `X-User-ID` into `approved_by_staff_id`, and splits the entry's minutes into a regular leg and an overtime leg. The split is decided against the staff member's already-approved workload on the same UTC date: let *prior minutes* be the sum of `minutes` across every **other** time entry of the same `staff_id` on the same `work_date` that is billable and whose status is `APPROVED` or `BILLED` — submitted entries and non-billable entries are excluded, so the order in which a day's entries are approved is what decides which one absorbs the overtime. The regular allowance for the day is eight hours, that is 480 minutes. `regular_minutes` is therefore that 480-minute threshold minus the prior minutes, clamped so that it never exceeds this entry's own minutes and never falls below zero; `overtime_minutes` is the entry's minutes less `regular_minutes`. So a person carrying 479 prior minutes who submits a 2-minute entry gets exactly 1 regular minute and 1 overtime minute, and a person already at 480 prior minutes sees the whole entry priced as overtime.

`billable_amount_cents` is then assembled from the two legs, each rounded on its own before they are added: the regular leg is `regular_minutes` multiplied by `pinned_rate_cents_per_hour` divided by 60, rounded half up to a whole cent; the overtime leg is `overtime_minutes` multiplied by `pinned_rate_cents_per_hour`, multiplied by the overtime multiplier of 1.5 (time-and-a-half), divided by 60, and rounded half up to a whole cent; and `billable_amount_cents` is the sum of the two rounded results. If the entry is not billable, `regular_minutes`, `overtime_minutes` and `billable_amount_cents` are all 0.

An approved entry later moves `APPROVED → BILLED` when a final invoice that includes it is issued, and reverts `BILLED → APPROVED` if that invoice is subsequently voided — the compensating move that releases the line to be billed again. A provisional invoice never moves an entry to `BILLED`. Time entries may be listed and filtered by `campaign_id`, by `staff_id`, by `approved_by_staff_id`, and by `status`.

### 3.6. Vendor Pass-Through Costs

Freelancers, production houses and printers are billed through the agency, and the agency takes a markup. An `AccountManager` records a cost against a `campaign_id` with a non-empty `vendor_name`, a `vendor_type` of `FREELANCER`, `PRODUCTION`, `PRINT` or `OTHER`, the `incurred_on` date that decides which billing period the cost falls into, and the quoted `estimated_amount_cents` — a non-negative integer known at submission. The cost is stored as `SUBMITTED` with `actual_amount_cents` null. As with time, the owning campaign must be `IN_FLIGHT`, or the request meets `ERR_CAMPAIGN_ON_HOLD`.

When the supplier's own invoice arrives, an `AccountManager` approves the cost and supplies the `actual_amount_cents` the vendor really charged. That moves the cost `SUBMITTED → APPROVED` and records the actual figure. Estimated and actual figures are not interchangeable: provisional billing uses the estimate, final billing uses the actual. Like time entries, a vendor cost moves `APPROVED → BILLED` when a final invoice including it is issued, and reverts `BILLED → APPROVED` when that invoice is voided.

Whichever figure a given invoice picks up becomes that line's *base*. The markup rule is fixed by the governing statement of work's `markup_pct`, and the rounding order is part of the contract: **each line individually** is multiplied by one plus the markup rate and rounded half up to a whole cent, and only then are the marked-up lines summed into the invoice's `vendor_marked_up_cents`. The un-marked-up bases of the same lines are summed, without any rounding step, into `vendor_base_cents`. Summing the bases first and applying the markup once to the aggregate is a different — and wrong — answer: two lines of 1,000,002 cents at a 17.5 percent markup come to 2,350,004 cents when rounded per line and 2,350,005 cents when rounded after summing.

### 3.7. Media Planning and the Insertion-Order Budget Ledger

A `MediaBuyer` drafts a media plan against a `campaign_id`, declaring the total gross media budget it may commit as `approved_budget_cents` and a non-empty `allowed_channels` array whose members are drawn from `DISPLAY`, `VIDEO`, `SOCIAL`, `OOH` and `PRINT`. The plan is created in `DRAFT`, and its `uncommitted_cents` starts equal to `approved_budget_cents`. The advertiser's `ClientReviewer` signs the plan off — legal only from `DRAFT`, only on a campaign that is `IN_FLIGHT`, and only when `X-User-ID` matches that campaign's advertiser — moving it `DRAFT → APPROVED`. The plan reaches its terminal `LOCKED` state only through the wrap-up cascade of section 3.4, never by direct request. Media plans may be listed and filtered by `campaign_id` and by `status`; reading one is the canonical way to obtain the `version` that insertion-order creation demands.

An insertion order commits money out of a plan against one slot of publisher inventory. Creating one names the `media_plan_id`, the `placement_id` of the slot, the flight window, the `gross_cents` committed to the publisher (an integer of at least 1), and the `expected_media_plan_version` stale-version token of section 2.7. The flight window is a **closed** date interval: `flight_start` is the first day on air and `flight_end` is the last day on air, and both days are on air; `flight_end` must be on or after `flight_start`, so a single-day flight has the two dates equal.

Three rules govern the create beyond the stale-version guard. The slot's `channel` must be a member of the plan's `allowed_channels`, or the order is rejected with `ERR_PLACEMENT_NOT_ELIGIBLE`. The flight must not collide with another booking on the same slot: taking the placement's `min_dark_days` as a buffer, the new order conflicts with any other insertion order on the same `placement_id` whose status is `RESERVED`, `PLACED` or `DELIVERED` when the new flight's start falls on or before that existing flight's end extended forward by the dark-day buffer *and* the existing flight's start falls on or before the new flight's end extended forward by the same buffer. A conflict is rejected with `ERR_PLACEMENT_FLIGHT_CONFLICT`. A placement with a `min_dark_days` of 0 permits back-to-back flights but still forbids overlapping ones. Finally, the money must be there: the order's `gross_cents` must not exceed the plan's `uncommitted_cents` as it stands *before* the commitment. Exactly equal to the uncommitted balance is accepted; strictly greater is rejected with `ERR_MEDIA_BUDGET_EXCEEDED`.

An accepted order is created in `RESERVED`, and the plan's `uncommitted_cents` is reduced by the order's `gross_cents`; the plan's `version` moves with it. From `RESERVED` the buyer sends the order to the publisher, `RESERVED → PLACED`, which is legal only when the owning plan is `APPROVED` — a plan still in `DRAFT`, or already `LOCKED`, is rejected with `ERR_MEDIA_PLAN_NOT_APPROVED`. After the flight the buyer records the publisher's post-flight figures, moving `PLACED → DELIVERED` and setting `delivered_impressions` and `delivered_spend_cents` to the supplied values; until that point both read 0. `DELIVERED` is terminal.

Cancellation is the compensating action of creation and is legal from `RESERVED` and from `PLACED`. It moves the order to the terminal `CANCELLED` state and adds the order's `gross_cents` straight back into the plan's `uncommitted_cents`, incrementing both the order's and the plan's `version`. Note the asymmetry with the wrap-up cascade: locking a plan auto-cancels only its `RESERVED` orders, whereas an order already `PLACED` can be cancelled only by an explicit call. Insertion orders may be listed and filtered by `media_plan_id`, by `placement_id`, and by `status`.

### 3.8. Invoice Assembly, Issue, Void and Payment

An invoice is assembled by an `AccountManager` for exactly one campaign over a half-open period. The payload names the `client_id`, the `campaign_id` being billed, the `retainer_id` whose prepaid balance will be drawn down, a `billing_mode` of `PROVISIONAL` or `FINAL`, and the window `period_start` (inclusive) to `period_end` (exclusive, and strictly after the start). Both the campaign and the retainer must belong to the named advertiser, or the request is malformed. **Every money column is computed at assembly time; issuing never re-prices anything.**

Which rows the invoice picks up, and at what value, is entirely determined by `billing_mode` — and the two modes can produce very different money from identical data. The window itself is compared as a pair of UTC calendar dates: whatever time of day the caller writes into `period_start` and `period_end`, only their date parts are used, and a row falls inside the window when its own date (a time entry's `work_date`, a vendor cost's `incurred_on`, an insertion order's `flight_start`) is on or after the start date and strictly before the end date. Neither the campaign's state nor the retainer's state gates assembly: an invoice may be assembled for a campaign in any state, including one that is `ON_HOLD`, `WRAP_UP` or `CLOSED`.

- Under `PROVISIONAL`, the agency bills forecast values from work that has not yet been signed off. Time entries of the campaign whose `work_date` falls inside the window and whose status is `SUBMITTED` or `APPROVED` are included, each contributing its `estimated_amount_cents` — the straight-line figure with no overtime uplift. Vendor costs of the campaign whose `incurred_on` falls inside the window and whose status is `SUBMITTED` or `APPROVED` are included, each contributing its `estimated_amount_cents` as its base. Insertion orders belonging to any media plan of the campaign, whose `flight_start` falls inside the window, are included when their status is `RESERVED`, `PLACED` or `DELIVERED`.
- Under `FINAL`, the agency bills only approved work at actual values. Time entries in the window are included only when their status is `APPROVED`, and each contributes its `billable_amount_cents` — the figure *with* the overtime uplift. Vendor costs in the window are included only when their status is `APPROVED`, and each contributes its `actual_amount_cents` as its base. Insertion orders in the window are included only when their status is `PLACED` or `DELIVERED`.

`labor_cents` is the sum of the labour value of every included time entry, under whichever rule the mode selects. `vendor_base_cents` and `vendor_marked_up_cents` follow the per-line markup rule of section 3.6, applied to the bases the mode selects. `media_gross_cents` is the sum of `gross_cents` across the included insertion orders. `line_count` is the number of included time entries plus the number of included vendor costs plus one more if `media_gross_cents` is greater than zero. An invoice that assembles zero lines is not created at all: it is rejected with `ERR_INVOICE_NO_LINES`.

The agency's cut of media is a tiered commission on `media_gross_cents`. The commission rate is 15 percent while the gross is below 5,000,000 cents; 12 percent from 5,000,000 cents up to but not including 20,000,000 cents; and 10 percent from 20,000,000 cents upward. The tier boundaries are inclusive at the low end, so a gross of exactly 5,000,000 cents takes 12 percent (not 15) and a gross of exactly 20,000,000 cents takes 10 percent (not 12). The raw commission is the gross multiplied by the selected rate, rounded half up to a whole cent, and it is then clamped into a band: no less than 50,000 cents and no more than 2,500,000 cents. One exception overrides the band — when `media_gross_cents` is zero, `media_commission_cents` is zero, and the 50,000-cent floor does **not** apply.

The invoice total is then built in a strictly pinned order of five steps, and no other order produces the right answer:

1. `subtotal_cents` is `labor_cents` plus `vendor_marked_up_cents` plus `media_commission_cents`.
2. `discount_pct` is the volume-discount rate selected from `subtotal_cents` **and from nothing else**: 0.00 while the subtotal is below 10,000,000 cents; 0.05 from 10,000,000 cents up to but not including 25,000,000 cents; and 0.08 from 25,000,000 cents upward.
3. `discount_cents` is `subtotal_cents` multiplied by `discount_pct`, rounded half up to a whole cent.
4. `admin_fee_cents` is 3 percent of the *discounted* subtotal — that is, 0.03 multiplied by the difference of `subtotal_cents` and `discount_cents` — rounded half up to a whole cent. It is computed **after** the discount, never before.
5. `total_cents` is `subtotal_cents` less `discount_cents` plus `admin_fee_cents`.

The trap in that sequence is worth stating plainly: the discount tier keys on the subtotal, not on the total. A subtotal of 9,800,000 cents therefore takes a 0.00 discount and an admin fee of 294,000 cents, for a total of 10,094,000 cents. Keying the tier on that total — which does cross the 10,000,000-cent line — would wrongly grant the 5 percent band.

A new invoice sits in two independent state dimensions at once: `approval_status` is `DRAFT` and `payment_status` is `UNPAID`. `retainer_applied_cents`, `cash_due_cents` and `amount_paid_cents` are all 0, and `void_reason` is null. Invoices may be listed and filtered by `client_id`, by `campaign_id`, by `retainer_id`, and by `approval_status`.

**Issuing** is the `AgencyAdmin`'s act and the head of the system's longest cascade. It is legal only from `approval_status` `DRAFT` and requires the `expected_retainer_version` guard of section 2.7. It moves the invoice `DRAFT → ISSUED` and draws the retainer down: `retainer_applied_cents` is the smaller of the retainer's `balance_cents` and the invoice's `total_cents`, and `cash_due_cents` is `total_cents` less `retainer_applied_cents`. A `DEPLETED` retainer is not a barrier here — it simply contributes zero, and the whole total falls to cash. The retainer's `balance_cents` is then reduced by `retainer_applied_cents` and its `version` incremented. If that leaves the balance at exactly zero, the retainer moves `ACTIVE → DEPLETED`, which puts the advertiser `ACTIVE → CREDIT_HOLD`, which in turn freezes every `IN_FLIGHT` campaign of that advertiser to `ON_HOLD` — four hops in a single request. If the invoice's `billing_mode` is `FINAL`, every included time entry moves `APPROVED → BILLED` and every included vendor cost does the same; a `PROVISIONAL` invoice leaves both untouched. And if `cash_due_cents` comes out at zero — because the retainer covered the total in full — the invoice's payment dimension jumps immediately to `PAID`, and if the owning campaign is sitting in `WRAP_UP` it advances `WRAP_UP → CLOSED` on the spot.

**Voiding** is the exact inverse. It is legal only from `approval_status` `ISSUED` and only while `amount_paid_cents` is still 0 — an invoice against which any cash has been received cannot be voided, and the attempt is rejected with `ERR_INVALID_STATE`. Voiding moves the invoice `ISSUED → VOID` (a terminal state), records the supplied `reason` into `void_reason`, and adds `retainer_applied_cents` back onto the retainer's `balance_cents`, incrementing the retainer's `version`. If that revives a `DEPLETED` retainer, it moves `DEPLETED → ACTIVE`, which — provided every retainer of that advertiser is now `ACTIVE` — returns the advertiser `CREDIT_HOLD → ACTIVE` and releases its `ON_HOLD` campaigns back to `IN_FLIGHT`. Where the invoice was `FINAL`, every time entry and vendor cost it had billed reverts `BILLED → APPROVED`.

**Payment** moves only the second dimension. The advertiser's `ClientReviewer` — whose `X-User-ID` must equal the invoice's `client_id` — pays an `amount_cents` — an integer of at least 1 — against the invoice's `cash_due_cents`. The invoice must be `ISSUED`; paying an invoice whose approval dimension is anything else is rejected with `ERR_INVALID_STATE`. The payment adds `amount_cents` to `amount_paid_cents`, and the cumulative total must never exceed `cash_due_cents` — an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. The payment dimension then follows the money: `UNPAID` while `amount_paid_cents` is 0 and `cash_due_cents` is greater than 0; `PARTIALLY_PAID` once `amount_paid_cents` is greater than 0 but still short of `cash_due_cents`; and `PAID` once `amount_paid_cents` equals `cash_due_cents` exactly. A single payment that settles the whole balance goes `UNPAID → PAID` directly, while smaller payments walk `UNPAID → PARTIALLY_PAID → PAID`. The approval dimension stays `ISSUED` throughout — the two dimensions never interfere. Whenever the invoice reaches `PAID`, a campaign sitting in `WRAP_UP` is closed: `WRAP_UP → CLOSED`.

### 3.9. Utilization and Campaign Performance Reporting

Two computed reads close the loop between what the agency sold and what it actually did.

**Staff utilization** is read for one person over a half-open window supplied as the query parameters `period_start` and `period_end`. Both are mandatory, and `period_end` must be strictly after `period_start`; a missing, unparseable or inverted window is rejected with `ERR_INVALID_REQUEST`. It answers with the staff member's `staff_id`, the window it was asked about — echoed back as two `YYYY-MM-DD` calendar dates — and seven figures. The rows it counts are all of that person's time entries in the window whatever campaign they belong to. `capacity_minutes` is the number of UTC calendar dates in the window that fall on a Monday, Tuesday, Wednesday, Thursday or Friday, multiplied by that person's `standard_daily_capacity_minutes` — weekends contribute no capacity. `billable_minutes` is the sum of `minutes` across the person's time entries whose `work_date` falls in the window, that are billable, and whose status is `APPROVED` or `BILLED`. `logged_minutes` is the sum of `minutes` across the person's time entries whose `work_date` falls in the window and whose status is `SUBMITTED`, `APPROVED` or `BILLED` — every row, regardless of the `billable` flag. `billed_amount_cents` is the sum of `billable_amount_cents` over the same rows that `billable_minutes` counts.

From those, two utilization percentages are reported and they deliberately disagree on identical data. `utilization_pct_capacity_based` is `billable_minutes` divided by `capacity_minutes`, multiplied by 100 and rounded half up to one decimal place — or 0.0 when `capacity_minutes` is zero. Because its denominator is contracted capacity, both idle time and non-billable admin time drag it down. `utilization_pct_logged_based` is `billable_minutes` divided by `logged_minutes`, multiplied by 100 and rounded half up to one decimal place — or 0.0 when `logged_minutes` is zero. Because its denominator is what the person actually logged, idle time is invisible to it and only the billable-to-non-billable split moves it. Alongside them, `effective_billable_rate_cents_per_hour` is `billed_amount_cents` multiplied by 60 and divided by `billable_minutes`, rounded half up to a whole cent — or 0 when `billable_minutes` is zero.

**The campaign performance report** answers with the `campaign_id` and seven figures, and it is where the agency finds out whether the campaign made money. Only insertion orders belonging to a media plan of the campaign and sitting in `DELIVERED` contribute media figures: `delivered_impressions` is the sum of their `delivered_impressions` and `delivered_spend_cents` the sum of their `delivered_spend_cents`. `effective_cpm_cents` — the cost per thousand impressions actually achieved — is `delivered_spend_cents` multiplied by 1000 and divided by `delivered_impressions`, rounded half up to a whole cent; when no impressions were delivered it reports 0 rather than failing. On the revenue side, `billed_revenue_cents` is the sum of `total_cents` across every invoice of the campaign whose `approval_status` is `ISSUED` — voided invoices drop out entirely. On the cost side, `direct_cost_cents` is the sum of `internal_cost_cents` across the campaign's time entries whose status is `APPROVED` or `BILLED`, plus the sum of `actual_amount_cents` across the campaign's vendor costs whose status is `APPROVED` or `BILLED`; entries and costs still `SUBMITTED` are excluded, but non-billable time entries **do** contribute their internal cost — unbillable work is still work the agency paid for. `agency_gross_profit_cents` is `billed_revenue_cents` less `direct_cost_cents`, and `gross_margin_pct` is that profit divided by `billed_revenue_cents`, multiplied by 100 and rounded half up to one decimal place — or 0.0 when no revenue has been billed.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Creating a new resource answers with HTTP 201 and the created resource; every other successful call — reads, state transitions, edits — answers with HTTP 200 and the affected resource, except the computed reads and the clock endpoint, which answer with HTTP 200 and their own report shape. Request bodies, response bodies and side effects are not repeated here; they are specified in section 3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/clients` | Register an advertiser. | `AgencyAdmin` |
| GET | `/clients/{id}` | Read one advertiser, including its cascaded status. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, `ClientReviewer` |
| POST | `/rate-cards` | Publish a rate card. | `AgencyAdmin` |
| PATCH | `/rate-cards/{id}` | Edit the live rates on a rate card. | `AgencyAdmin` |
| POST | `/staff-members` | Register an agency employee. | `AgencyAdmin` |
| GET | `/staff-members/{id}/utilization` | Computed read of the dual-variant utilization figures over a half-open window. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer` |
| POST | `/media-placements` | Register a publisher inventory slot. | `AgencyAdmin` |
| POST | `/retainers` | Open a prepaid retainer for an advertiser. | `AgencyAdmin` |
| GET | `/retainers/{id}` | Read one retainer, including its balance and version. | `AgencyAdmin`, `AccountManager`, `ClientReviewer` |
| GET | `/retainers` | List retainers, filterable by client and status. | `AgencyAdmin`, `AccountManager`, `ClientReviewer` |
| POST | `/retainers/{id}/fund` | Top the retainer up with more cash. | `AgencyAdmin` |
| POST | `/sows` | Draft a statement of work referencing a rate card. | `AccountManager` |
| GET | `/sows/{id}` | Read one SOW, including its pinned rate snapshot and consumed labour. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, `ClientReviewer` |
| GET | `/sows` | List SOWs, filterable by client, rate card and status. | `AgencyAdmin`, `AccountManager`, `ClientReviewer` |
| POST | `/sows/{id}/countersign` | The advertiser signs the SOW, freezing the rate card onto it. | `ClientReviewer` |
| POST | `/campaigns` | Create a campaign under a SOW and record its brief. | `AccountManager` |
| GET | `/campaigns/{id}` | Read one campaign. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, `ClientReviewer` |
| GET | `/campaigns` | List campaigns, filterable by client, SOW and status. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, `ClientReviewer` |
| POST | `/campaigns/{id}/launch` | Take the campaign live. | `AccountManager` |
| GET | `/campaigns/{id}/deliverables` | Reverse lookup of every deliverable of this campaign. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer`, `ClientReviewer` |
| GET | `/campaigns/{id}/vendor-costs` | Reverse lookup of every vendor cost of this campaign. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| GET | `/campaigns/{id}/performance-report` | Computed read: delivered media, effective CPM, issued revenue, direct cost and gross margin. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| POST | `/deliverables` | Open a creative deliverable on a campaign. | `CreativeLead` |
| POST | `/deliverables/{id}/submit` | Submit a new asset cut for client review. | `CreativeLead` |
| POST | `/deliverables/{id}/request-changes` | The advertiser bounces the cut back to the creative team. | `ClientReviewer` |
| POST | `/deliverables/{id}/approve` | The advertiser approves the current cut. | `ClientReviewer` |
| POST | `/time-entries` | Log a worked interval against a campaign. | `AccountManager`, `CreativeLead`, `MediaBuyer` |
| GET | `/time-entries/{id}` | Read one time entry. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer` |
| GET | `/time-entries` | List time entries, filterable by campaign, logger, approver and status. | `AgencyAdmin`, `AccountManager`, `CreativeLead`, `MediaBuyer` |
| POST | `/time-entries/{id}/approve` | Approve someone else's logged time and price its overtime. | `AccountManager` |
| POST | `/vendor-costs` | Record a freelancer or production pass-through cost. | `AccountManager` |
| POST | `/vendor-costs/{id}/approve` | Approve the supplier invoice and record the actual charge. | `AccountManager` |
| POST | `/media-plans` | Draft a media-buy plan with a budget and a channel whitelist. | `MediaBuyer` |
| GET | `/media-plans/{id}` | Read one media plan, including its uncommitted budget and version. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| GET | `/media-plans` | List media plans, filterable by campaign and status. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| POST | `/media-plans/{id}/approve` | The advertiser signs the media plan off. | `ClientReviewer` |
| POST | `/insertion-orders` | Reserve publisher inventory, committing budget out of the plan. | `MediaBuyer` |
| GET | `/insertion-orders/{id}` | Read one insertion order. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| GET | `/insertion-orders` | List insertion orders, filterable by media plan, placement and status. | `AgencyAdmin`, `AccountManager`, `MediaBuyer`, `ClientReviewer` |
| POST | `/insertion-orders/{id}/place` | Send the order to the publisher. | `MediaBuyer` |
| POST | `/insertion-orders/{id}/cancel` | Cancel the order and release its committed budget. | `MediaBuyer` |
| POST | `/insertion-orders/{id}/deliver` | Record the publisher's post-flight delivery figures. | `MediaBuyer` |
| POST | `/invoices` | Assemble a draft invoice for one campaign over a half-open period. | `AccountManager` |
| GET | `/invoices/{id}` | Read one invoice with every money column and both state dimensions. | `AgencyAdmin`, `AccountManager`, `ClientReviewer` |
| GET | `/invoices` | List invoices, filterable by client, campaign, retainer and approval status. | `AgencyAdmin`, `AccountManager`, `ClientReviewer` |
| POST | `/invoices/{id}/issue` | Issue the invoice and draw the retainer down. | `AgencyAdmin` |
| POST | `/invoices/{id}/void` | Void an unpaid issued invoice. | `AgencyAdmin` |
| POST | `/invoices/{id}/payments` | The advertiser pays cash against the invoice's cash due. | `ClientReviewer` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and expire any SOWs the move retires. | `AgencyAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_RATE_CARD_NOT_FOUND` | 404 |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 |
| `ERR_RETAINER_NOT_FOUND` | 404 |
| `ERR_SOW_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_TIME_ENTRY_NOT_FOUND` | 404 |
| `ERR_VENDOR_COST_NOT_FOUND` | 404 |
| `ERR_MEDIA_PLAN_NOT_FOUND` | 404 |
| `ERR_MEDIA_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_INSERTION_ORDER_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOW_NOT_COUNTERSIGNED` | 409 |
| `ERR_SOW_EXPIRED` | 409 |
| `ERR_CAMPAIGN_ON_HOLD` | 409 |
| `ERR_MEDIA_PLAN_NOT_APPROVED` | 409 |
| `ERR_PLACEMENT_FLIGHT_CONFLICT` | 409 |
| `ERR_TIME_ENTRY_OVERLAP` | 409 |
| `ERR_PLACEMENT_NOT_ELIGIBLE` | 422 |
| `ERR_DAILY_MINUTES_EXCEEDED` | 422 |
| `ERR_SOW_LABOR_CAP_EXCEEDED` | 422 |
| `ERR_MEDIA_BUDGET_EXCEEDED` | 422 |
| `ERR_REVISION_LIMIT_EXCEEDED` | 422 |
| `ERR_INVOICE_NO_LINES` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_STALE_MEDIA_PLAN_VERSION` | 412 |
| `ERR_STALE_RETAINER_VERSION` | 412 |
