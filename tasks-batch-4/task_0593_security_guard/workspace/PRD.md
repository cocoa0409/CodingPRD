# Security Guard Services API — Product Requirements Document

## 1. Introduction

Contract security is a business of thin margins and hard promises. A client buys a guarded lobby for a fixed number of hours at a contracted rate; the provider staffs that lobby with a licensed officer, pays that officer a wage that must stay comfortably below the rate, and proves — through timestamps and NFC checkpoint taps — that the promise was actually kept. Every part of that chain can break. A guard's state licence expires overnight and nobody notices until an inspector arrives. A scheduler double-books an officer across two sites. An officer no-shows at 22:00 and the post stands empty until morning. An account manager issues an invoice that, once payroll is reckoned, turns out to have been billed below cost.

The Security Guard Services API exists to make each of those failures a rejected request rather than a discovered loss. It models the full operational spine of a guarding contract: the **client** and their **sites**, the **posts** at those sites with their bill rates and NFC tours, the written **post orders** briefed to the officer on duty, the **guards** with their licences and training certifications, the **coverage shifts** those guards work, the **tour scans** and **incident reports** they generate in the field, and finally the **invoices** that turn verified shifts into money — checked, before issuance, against the gross-margin floor the client's contract demands.

Two design commitments run through everything that follows. First, the system runs on a **logical clock**, not wall-clock time: every stamped instant, every expiry decision, every no-show grace check reads from a clock the platform controls, so that scheduling behaviour is exactly reproducible. Second, **expiry and coverage risk are swept, never inferred lazily** — a licence does not silently lapse the moment its expiry instant passes; it lapses when a compliance sweep runs and cascades that lapse through the guard's licence dimension, their future shifts, and the coverage status of every site those shifts belonged to.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if the value of `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else in the request pipeline.

The six roles are `AccountManager`, `Scheduler`, `Guard`, `FieldSupervisor`, `ComplianceOfficer`, and `PlatformAdmin`.

- An `AccountManager` owns the client-facing surface: clients, sites, posts, post orders and invoices.
- A `Scheduler` builds the coverage schedule and assigns guards to posts.
- A `Guard` is the security officer on the ground: they confirm their shifts, clock in and out, tap NFC checkpoints and file incident reports.
- A `FieldSupervisor` provides field oversight: declaring no-shows, verifying completed shifts, and reviewing, escalating, resolving and closing incidents.
- A `ComplianceOfficer` owns guard records, licensing, training certifications and the expiry sweep.
- A `PlatformAdmin` operates the logical clock and holds broad read access, but no business write powers.

Once the role is recognised, the second gate asks whether that role is permitted to perform the requested operation. Several endpoints in this system are multi-action — a single write endpoint accepts an `action` value that selects among several lifecycle transitions — and role permission is evaluated against the *specific* action, not merely against the endpoint. A `Guard` may present a shift action, but only the `CONFIRM` action; a `Scheduler` may present `CONFIRM`, `UNASSIGN` or `CANCEL`; only a `FieldSupervisor` may present `NO_SHOW` or `VERIFY`. On incident actions, `SUBMIT` belongs to the `Guard` and `REVIEW`, `ESCALATE`, `REQUEST_INFO`, `RESOLVE` and `CLOSE` belong to the `FieldSupervisor`. Every invoice action belongs to the `AccountManager`. A role acting outside its grant — whether at the endpoint level or at the action level — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

**Identity semantics.** When `X-User-Role` is `Guard`, `X-User-ID` is the `id` of the acting `Guard` entity; ownership checks on any resource that references a `Guard` compare the resource's foreign-key field to `X-User-ID`. Concretely, a shift being confirmed, clocked into, clocked out of, or scanned against must carry the acting officer's identifier in its `guard_id`, and an incident report filed or re-submitted by an officer must belong to a shift whose `guard_id` is that officer. A mismatch is rejected with `ERR_NOT_SHIFT_OWNER` (HTTP 403).

When `X-User-Role` is `AccountManager`, `Scheduler`, `FieldSupervisor`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `verified_by_user_id` on a credential a `ComplianceOfficer` verifies, or as `escalated_by_user_id` and `closed_by_user_id` on an incident a `FieldSupervisor` escalates and closes — but it never compares it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` skips the given number of records and defaults to 0; it may not be negative. A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 422).

Every list endpoint returns its records sorted by `created_at` in ascending order unless a narrative elsewhere in this document names a different ordering for a derived collection.

List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope. `total_count` reports the number of records matching the filters before the window is applied; `has_more` is true when records remain beyond the current window.

### 2.4. The Logical Clock

Nothing in this system reads the machine's wall clock. The server maintains a single **logical clock** whose value at process start is exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. Every instant the server itself stamps — a clock-in, a clock-out, an NFC scan, a post-order publication, a credential verification, a compliance sweep, an invoice issuance, a shift verification — is read from that logical clock. Every temporal comparison — is this licence expired, is this shift starting within the next 48 hours, has the no-show grace period elapsed — is likewise made against that logical clock.

A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant; the operation echoes back the new `current_utc`. Advancing the clock is inert on its own: it does not by itself expire credentials, flip a guard's licensing dimension, release shifts, or recompute site coverage. Those consequences follow only when a compliance sweep is run.

### 2.5. Common Resource Properties

Clients, sites, posts, post orders, guards, credentials, coverage shifts, incident reports, invoices and invoice lines each carry a standard set of system-managed properties:

- `id` — a server-minted UUID. It carries no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recorded when the record was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the record.
- `version` — an integer that starts at 1 and increments by one on every mutation of the record.

A recomputation of a derived field counts as a mutation for these purposes: when a guard's committed hours are recalculated, or a site's coverage status flips, or an invoice's total is re-derived after a credit, the affected record's `updated_at` is refreshed and its `version` increments.

Tour scans are the one exception. A tour scan is an immutable field observation: it carries `id` and `created_at` only. It has **no** `updated_at` and **no** `version`.

### 2.6. Version Pinning and Optimistic Concurrency Control

Two write operations in this system are guarded by optimistic concurrency control, and both are guarded for the same structural reason: the target entity legitimately accepts repeated writes, so no state precondition can distinguish a fresh request from one built on a stale read.

The first is **assigning a guard to a coverage shift**, which is served by `POST /shifts/{id}/assignments`. The request must carry `expected_shift_version`, a non-optional field holding the `version` of the `CoverageShift` the client last observed. Because a shift already in `SCHEDULED` may legitimately be reassigned — a later assignment supersedes the earlier one — there is no state check that would catch a client working from an outdated view. If `expected_shift_version` does not equal the shift's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second is **drafting a post order against a post**, served by `POST /post-orders`. The request must carry `expected_post_version`, a non-optional field holding the `version` of the `Post` the client last observed. A post legitimately accepts successive post-order revisions, so again no state precondition catches a stale client; only the version check does. If `expected_post_version` does not equal the post's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful post-order creation increments the post's `version` by one, which is precisely why a second create issued from the same stale read will fail.

No other endpoint in this API accepts a version field, and no other endpoint performs a version check.

Distinct from optimistic concurrency, and not to be confused with it, is the **briefing pin**: a coverage shift, at the moment it is confirmed, captures both the identifier and the version of the post order the officer was briefed on, into `pinned_post_order_id` and `pinned_post_order_version`. That pin is a historical record, not a concurrency guard, and later republication on the post never rewrites it.

### 2.7. Money, Hours and Rounding Discipline

Money is carried in **integer cents** throughout. There are no fractional cents anywhere in the model. Wherever a monetary quantity is derived by multiplication or by taking a percentage, the result is rounded **half up** to a whole cent.

Hours are carried as numbers with **two decimal places**, rounded half up. So are percentages: tour compliance, invoice margin and the reliability scores are all two-decimal numbers rounded half up.

One rounding-order rule is absolute and applies wherever hours are converted into money: **round the hours first, then multiply by the rate, then round the cents.** Un-rounded hours are never multiplied by a rate. Where a rate is itself adjusted by a multiplier — as the night differential does — the adjusted rate is rounded to whole cents *before* it is multiplied by hours.

Billing and pay deliberately round hours in *different* directions, and the divergence is intentional: billing always rounds the worked interval **up** to the next quarter hour, on the principle that the client is billed for the quarter the officer started; pay rounds the worked interval to the **nearest** quarter hour, half up. A shift worked for 7 hours and 5 minutes is therefore billed as 7.25 hours and paid as 7.00 hours.

### 2.8. Request Validation Order

The API evaluates every request through a fixed pipeline, and the order matters because several checks would otherwise mask one another. The sequence is:

1. **Authentication.** `X-User-ID` and `X-User-Role` present, and the role recognised — otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorisation.** The role is permitted for the endpoint and, on multi-action endpoints, for the specific `action` value — otherwise `ERR_FORBIDDEN_ROLE`.
3. **Schema validation.** Required fields present, enum members valid, numbers within their declared ranges, `scheduled_end_at` strictly later than `scheduled_start_at`, `period_end` strictly later than `period_start`, `limit` within 1 to 100 inclusive, `offset` not negative, and the free-text fields `narrative`, `note` and `dispute_reason` non-empty where supplied — otherwise `ERR_VALIDATION`.
4. **Existence.** Every referenced identifier resolves to a real record. Path identifiers are resolved first, then body identifiers, each group left-to-right in declaration order. The failure carries the not-found code of the *first* identifier that fails to resolve: `ERR_CLIENT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_POST_ORDER_NOT_FOUND`, `ERR_GUARD_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`, each HTTP 404.
5. **Guard ownership.** Where the acting role is `Guard`, the officer owns the shift being acted on — `ERR_NOT_SHIFT_OWNER`.
6. **Optimistic concurrency.** `expected_shift_version` or `expected_post_version` matches the parent's current `version` — `ERR_STALE_VERSION`.
7. **State admissibility.** The target's current status admits the requested transition — `ERR_INVALID_STATE`.
8. **Assignment presence.** The shift has an assigned guard where the action requires one — `ERR_SHIFT_NOT_ASSIGNED`.

Beyond step 8 come the domain gates, and their relative order is likewise fixed: employment status (`ERR_GUARD_NOT_ACTIVE`), then licensing (`ERR_GUARD_NOT_LICENSED`), then certification coverage (`ERR_GUARD_CERT_MISSING`), then the published-post-order requirement (`ERR_POST_ORDER_NOT_PUBLISHED`), then checkpoint-tag membership (`ERR_UNKNOWN_CHECKPOINT_TAG`), then the officer's overlap check (`ERR_GUARD_DOUBLE_BOOKED`), then the officer's rest-period check (`ERR_GUARD_REST_PERIOD_VIOLATION`), then post capacity (`ERR_POST_CAPACITY_EXCEEDED`), then employee-code uniqueness (`ERR_DUPLICATE_EMPLOYEE_CODE`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and finally the three fiscal gates in the order: at least one invoice line (`ERR_INVOICE_NO_BILLABLE_SHIFTS`), credit within the line (`ERR_CREDIT_EXCEEDS_LINE`), margin at or above the floor (`ERR_MARGIN_BELOW_FLOOR`).

The practical consequence: a stale shift version surfaces as `ERR_STALE_VERSION` even when the guard named in the payload is also unlicensed, and a suspended guard surfaces as `ERR_GUARD_NOT_ACTIVE` even when they also lack a required certification.

### 2.9. Cascade Discipline and Derived-Field Freshness

Derived fields in this system are **eagerly recomputed at the moment of the event that could change them**, never lazily computed on read. Two derived quantities carry the heaviest cascade load and are worth naming here.

`Guard.committed_hours` is the total scheduled workload an officer currently stands committed to. It is recomputed whenever a shift is assigned, reassigned, unassigned, cancelled, declared a no-show, clocked out of, or released by a suspension, termination or compliance sweep. Assignment and unassignment are exact compensating operations: assigning an officer to a shift and then unassigning them returns `committed_hours` to precisely its pre-assignment value and leaves the shift back in `OPEN_UNFILLED` with `guard_id` and `pay_rate_cents_per_hour` both null.

`Site.coverage_status` is the site's staffing-risk flag. It is recomputed whenever any shift on any post of that site is created, assigned, unassigned or transitioned, and on every compliance sweep.

One further consequence of the eager model is worth stating plainly, because it is counter-intuitive: a guard's licensing dimension is recomputed **only** on credential creation, on credential verification, and on a compliance sweep. It is never recomputed on read. A verified licence whose expiry instant has already passed, but which no sweep has yet touched, therefore still leaves its holder in `LICENSED` — and that officer will still pass the licensing gate at assignment. Expiry is swept, not inferred.

### 2.10. Segregation of Duties

Field oversight in this business is deliberately not a one-person job. When an incident report has been escalated, the supervisor who escalated it may not be the supervisor who closes it. The system remembers the escalating operator's `X-User-ID` and refuses a close request bearing the same identifier with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An incident that was never escalated carries no such restriction and any `FieldSupervisor` may close it.

## 3. Business Logic & Workflows

### 3.1. Clients, Sites and Guard Posts

Everything the business does hangs off a **client**. An `AccountManager` registers one by supplying its legal `name` — a non-empty string of at most 120 characters — and, optionally, a `margin_floor_pct`: the minimum gross-margin percentage an invoice must reach before it may be issued to this client. When the account manager does not name a floor, the system applies 20.0. The floor is a percentage and must sit between 0.0 and 100.0, both endpoints inclusive. A newly registered client's ledger fields, `outstanding_balance_cents` and `paid_to_date_cents`, both start at zero.

Those two ledger fields are derived, never written directly. `outstanding_balance_cents` is the sum of `total_cents` across the client's invoices whose status is `ISSUED`, `DISPUTED` or `ADJUSTED`. `paid_to_date_cents` is the sum of `total_cents` across the client's invoices whose status is `PAID`. Invoices in `DRAFT` and invoices in `VOID` contribute to neither. Both are recomputed on every invoice transition, and together they conserve money: issuing an invoice and then voiding the same invoice restores both fields to exactly their pre-issue values.

Beneath a client sit its **sites** — the physical properties under guard. An `AccountManager` creates a site with a payload naming the owning `client_id` and the site's non-empty `name`. Its `coverage_status` starts at `COVERED` and is one of exactly two values, `COVERED` or `AT_RISK`. A site is `AT_RISK` when at least one coverage shift on any post of that site currently sits in `OPEN_UNFILLED` and is scheduled to begin at or after the current logical clock instant and strictly before that instant plus 48 hours; if no such gap exists, the site is `COVERED`. Shifts that have already started, and shifts more than 48 hours out, are ignored by this test — the flag is about the imminent staffing hole, not the whole calendar. Sites may be listed with an optional `client_id` filter and an optional `coverage_status` filter.

Within a site are its **posts** — the actual guarded positions, "North Lobby" and the like. An `AccountManager` creates a post against a `site_id` with a display `name` and a `bill_rate_cents_per_hour`, the contracted client rate for that position, which must be at least 1. Four further attributes may be supplied and each has a default. `max_concurrent_guards` is the post's aggregate capacity — how many non-cancelled shifts may occupy any single instant on it — and it defaults to 1, with a minimum of 1. `required_cert_codes` is an array of uppercase training-certification codes an officer must hold in verified, unexpired form to be assigned or confirmed on the post; it defaults to the empty array. `checkpoint_tag_uids` is the ordered list of unique, non-empty NFC tag UIDs that make up the post's guard tour, and it too defaults to the empty array — a post with an empty tour is entirely legitimate. `tour_compliance_floor_pct` is the tour-compliance percentage at or above which no service credit is applied to the shift's final bill; it defaults to 80.0 and must sit between 0.0 and 100.0 inclusive. Posts may be listed with an optional `site_id` filter.

### 3.2. Post Orders and the Briefing Pin

A **post order** is the written instruction sheet handed to the officer standing a post: what to watch for, whom to call, when to walk the tour. An `AccountManager` drafts one by supplying the `post_id`, the `expected_post_version` described in §2.6, the non-empty `body_text` of the instructions, and a human `revision_label` such as "REV-C". The document is created in `DRAFT` status, its `published_at` null, and the parent post's `version` is incremented by one.

A post order lives through exactly three states: `DRAFT`, `PUBLISHED`, and the terminal `SUPERSEDED`. Publication is an `AccountManager` action and is admissible only from `DRAFT`; presenting it against a document in any other status is rejected with `ERR_INVALID_STATE`. On publication, the document's `status` moves `DRAFT → PUBLISHED` and its `published_at` is stamped from the logical clock. In the same operation, any *other* post order on the same post that was sitting in `PUBLISHED` transitions `PUBLISHED → SUPERSEDED`. A post therefore has at most one published document at any instant, which is what lets shift confirmation speak of "the post's published post order" without ambiguity.

Superseding is deliberately gentle on history. A superseded document remains fully readable, and — critically — it remains the pinned briefing document of every shift that pinned it. Publishing a fresh revision does **not** rewrite `pinned_post_order_id` or `pinned_post_order_version` on shifts that were already `CONFIRMED`: an officer is held to the instructions they were actually briefed on, not to the ones that landed after they confirmed. Post orders may be listed with optional `post_id` and `status` filters.

### 3.3. The Guard Record: Two Dimensions, Licences and Certifications

A `ComplianceOfficer` creates a **guard** record with a `full_name`, an `employee_code` and a `pay_rate_cents_per_hour` of at least 1. The `employee_code` is the employer-assigned identifier and must be unique across every guard in the system; a second guard bearing an existing code is rejected with `ERR_DUPLICATE_EMPLOYEE_CODE`.

A guard carries **two independent state dimensions on the same record**, and neither is a function of the other. The employment dimension, `employment_status`, is one of `APPLICANT`, `ACTIVE`, `SUSPENDED` or `TERMINATED`, starting at `APPLICANT`, with `TERMINATED` terminal. The licensing dimension, `license_status`, is one of `UNLICENSED`, `PENDING_VERIFICATION`, `LICENSED` or `EXPIRED`, starting at `UNLICENSED`. They evolve through entirely different triggers, and eligibility to work a shift is the *conjunction* of the two: an officer must be both `ACTIVE` and `LICENSED`.

The employment dimension is driven by a `ComplianceOfficer` presenting one of four `action` values against the guard. `ACTIVATE` carries `APPLICANT` to `ACTIVE`, and is admissible only when the officer's `license_status` is already `LICENSED` — an unlicensed applicant cannot be activated, and the attempt is rejected with `ERR_GUARD_NOT_LICENSED`. `SUSPEND` carries `ACTIVE` to `SUSPENDED`. `REINSTATE` carries `SUSPENDED` back to `ACTIVE`. `TERMINATE` carries either `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED`. What suspension and reinstatement mean for reliability is the subject of §3.8; what termination and suspension mean for the schedule is stated there too.

The licensing dimension is not driven by any direct action at all. It is a **projection over the officer's credentials**, recomputed on exactly three occasions: when a credential is created, when a credential is verified, and when a compliance sweep runs. The projection looks only at the officer's `LICENSE` credentials — training certifications never move this dimension — and resolves in strict order: if any licence credential is `VERIFIED` and its `expires_at` is strictly later than the current logical clock, the officer is `LICENSED`; otherwise, if any licence credential is `PENDING_VERIFICATION`, the officer is `PENDING_VERIFICATION`; otherwise, if any licence credential is `EXPIRED`, the officer is `EXPIRED`; otherwise, with no licence credentials at all, the officer is `UNLICENSED`. The design pin in §2.9 bears repeating here: because the projection runs on only those three triggers, a verified licence that has drifted past its expiry instant without a sweep still leaves its holder `LICENSED`.

A **credential** is recorded by a `ComplianceOfficer` with the holder's `guard_id`, a `kind` of either `LICENSE` or `CERTIFICATION`, a non-empty uppercase `code` — a licence class such as "GUARD_CARD", or a training code such as "CPR" — the issuing authority's `credential_number`, and an `expires_at` instant. It is created in `PENDING_VERIFICATION`, one of the three credential statuses alongside `VERIFIED` and `EXPIRED`, with `verified_by_user_id` null. Recording a `LICENSE` credential triggers a recompute of the holder's licensing dimension, which is how a brand-new applicant moves from `UNLICENSED` to `PENDING_VERIFICATION`.

Verification is likewise a `ComplianceOfficer` operation and is admissible only when the credential's `status` is `PENDING_VERIFICATION` and its `expires_at` is strictly later than the current logical clock; verifying an already-verified credential, or one whose expiry has passed, is rejected with `ERR_INVALID_STATE`. On success the credential moves `PENDING_VERIFICATION → VERIFIED`, its `verified_by_user_id` records the acting operator's `X-User-ID`, and the holder's licensing dimension is recomputed — which, for an unexpired licence, carries the officer to `LICENSED`. This is also the road back from lapse: an officer sitting at `EXPIRED` returns to `LICENSED` when a fresh licence credential with a future `expires_at` is verified. Credentials may be listed with optional `guard_id`, `kind` and `status` filters.

The **compliance sweep** is the mechanism that makes expiry real, and only a `ComplianceOfficer` may run it. It takes no payload and reports back four counters: `swept_at`, the logical instant at which it ran; `expired_credential_count`; `unassigned_shift_count`; and `at_risk_site_count`. The sweep runs a four-hop cascade. First, every credential whose `status` is `VERIFIED` and whose `expires_at` is at or before the current logical clock transitions `VERIFIED → EXPIRED`. Second, each newly expired credential forces a recompute of its holder's licensing dimension, which for a lapsed licence-holder with no other valid licence yields `EXPIRED`. Third, for every officer whose licensing dimension has thereby left `LICENSED`, every one of their shifts sitting in `SCHEDULED` or `CONFIRMED` whose `scheduled_start_at` is at or after the current logical clock is released back to `OPEN_UNFILLED` — `guard_id`, `pay_rate_cents_per_hour`, `pinned_post_order_id` and `pinned_post_order_version` all cleared to null — and the officer's `committed_hours` is recomputed. Fourth, every site touched by a released shift has its `coverage_status` recomputed, and flips to `AT_RISK` when the released shift begins within 48 hours of the current clock. The sweep also refreshes licensing projections and coverage flags across the estate, which is why it is the intended way to bring the world into agreement with a clock that has just jumped forward.

### 3.4. Building the Coverage Schedule

A `Scheduler` opens a coverage gap on the calendar by creating a **coverage shift** against a `post_id`, with a `scheduled_start_at` and a `scheduled_end_at`. The interval is half-open: the start instant belongs to the shift, the end instant does not. `scheduled_end_at` must be strictly later than `scheduled_start_at`, and a payload violating that is rejected with `ERR_VALIDATION`. Two optional fields complete the payload. `planned_break_minutes` is the unpaid, unbilled break time deducted from both scheduled and actual hours; it defaults to 30 and may not be negative. `relief_for_shift_id` points at another shift on the same post that this new shift exists to relieve — the answer to a no-show, discussed in §3.8.

The shift is born in `OPEN_UNFILLED`, the first of eight statuses: `OPEN_UNFILLED`, `SCHEDULED`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, `VERIFIED`, `NO_SHOW` and `CANCELLED`, of which `VERIFIED` and `CANCELLED` are terminal. At creation it takes a snapshot of `bill_rate_cents_per_hour` from its post — the shift bills at the rate that was contracted when it was scheduled, and a later edit to the post never reaches back into an existing shift. Its `guard_id` and `pay_rate_cents_per_hour` are null; so are `pinned_post_order_id`, `pinned_post_order_version`, `actual_clock_in_at`, `actual_clock_out_at`, `billable_hours`, `paid_hours`, `final_billable_cents`, `pay_cents`, `margin_cents`, `tour_compliance_pct` and `verified_at`. Its `sla_credit_cents` starts at 0 and its `overtime_hours` at 0.0.

Two quantities are computed immediately at creation. **`scheduled_hours`** is the length of the scheduled interval in hours — the difference between `scheduled_end_at` and `scheduled_start_at`, expressed in hours — less the planned break, itself expressed in hours by dividing `planned_break_minutes` by 60; the result is rounded half up to two decimal places. **`provisional_billable_cents`** is the client-facing estimate: `scheduled_hours` multiplied by the shift's snapshotted `bill_rate_cents_per_hour`, rounded half up to a whole cent. The provisional estimate is deliberately naive — no quarter-hour ceiling, no overrun cap, no service credit — which is why a shift that runs twelve minutes long and misses a checkpoint will end up billing a different amount than its provisional figure ever suggested.

Creation is gated by **post capacity**. Count the shifts already on this post whose status is neither `CANCELLED` nor `NO_SHOW` and whose half-open interval strictly intersects the new shift's half-open interval, excluding from that count the shift named by `relief_for_shift_id` if one was supplied. That count must be strictly less than the post's `max_concurrent_guards`; otherwise the create is rejected with `ERR_POST_CAPACITY_EXCEEDED`. Adjacency is not intersection: a shift ending at exactly the instant another begins does not overlap it, and the two may sit back-to-back on a single-capacity post with no buffer at all. The relief exclusion is what makes the relief workflow possible: without it, a relief shift covering the same window as the no-show it replaces would be blocked by the very shift it exists to replace.

Creating a shift recomputes the site's `coverage_status` — a fresh unfilled shift starting within 48 hours is exactly what puts a site `AT_RISK`. Shifts may be listed with optional `post_id`, `guard_id`, `relief_for_shift_id`, `pinned_post_order_id` and `status` filters.

### 3.5. Assignment, Reassignment and Confirmation

Filling a gap is a `Scheduler` operation: an assignment names the `guard_id` of the officer to be crewed onto the shift, together with the `expected_shift_version` demanded by §2.6. A successful assignment on a shift sitting in `OPEN_UNFILLED` carries it `OPEN_UNFILLED → SCHEDULED`. The same operation applied to a shift already sitting in `SCHEDULED` is a **reassignment**: the new assignment legitimately supersedes the prior one and the shift remains in `SCHEDULED`.

Six preconditions guard the assignment, and they are evaluated in the order §2.8 fixes. The version check comes first. Then the officer's employment dimension must read `ACTIVE`, or the request fails with `ERR_GUARD_NOT_ACTIVE`. Then their licensing dimension must read `LICENSED`, or it fails with `ERR_GUARD_NOT_LICENSED`. Then the officer must hold, for every code listed in the post's `required_cert_codes`, a `CERTIFICATION` credential that is `VERIFIED` and whose `expires_at` is still in the future — a missing or lapsed training certification fails with `ERR_GUARD_CERT_MISSING`. Then comes the double-booking check: no other shift of that officer, in any status other than `CANCELLED` or `NO_SHOW`, may have a half-open interval that strictly intersects this shift's interval; a violation is `ERR_GUARD_DOUBLE_BOOKED`. Touching endpoints do not intersect — an officer may work a shift ending at 06:00 and another beginning at 06:00 without triggering this check.

They may not, however, work both under the **rest-period rule**. Beyond bare overlap, the officer must have at least eight hours of rest separating any two of their shifts. Concretely: widen this shift's interval by 480 minutes at *both* ends, and no other shift of that officer in a status other than `CANCELLED` or `NO_SHOW` may intersect the widened window. A violation is rejected with `ERR_GUARD_REST_PERIOD_VIOLATION`. The boundary is exact — a gap of exactly 480 minutes between the two intervals is compliant; a gap of 479 minutes is not. The 06:00-to-06:00 back-to-back pairing that survives the overlap check therefore dies here, which is the intended result.

A successful assignment does five things. It sets the shift's `guard_id` to the named officer. It snapshots the shift's `pay_rate_cents_per_hour` from that officer's current `pay_rate_cents_per_hour` — the shift pays at the wage in force when the officer was crewed onto it, and a later raise does not reach back. It increments the shift's `version` by one. It recomputes the officer's `committed_hours`. And it recomputes the site's `coverage_status`. On a reassignment, both `guard_id` and `pay_rate_cents_per_hour` are replaced with the incoming officer's values, and `committed_hours` is recomputed for **both** officers — falling for the one who was displaced, rising for the one who took the shift.

Releasing a shift is the compensating half. A `Scheduler` may present the `UNASSIGN` action against a shift in `SCHEDULED`, in `CONFIRMED`, or in `NO_SHOW`, and in each case the shift returns to `OPEN_UNFILLED`. The action requires that the shift actually have an assigned officer; if `guard_id` is null the request is rejected with `ERR_SHIFT_NOT_ASSIGNED`. Releasing from `SCHEDULED` clears `guard_id` and `pay_rate_cents_per_hour` to null, recomputes the released officer's `committed_hours`, and recomputes the site's `coverage_status`. Releasing from `CONFIRMED` does all of that and additionally clears `pinned_post_order_id` and `pinned_post_order_version` — the briefing is void because the briefing was for an officer who is no longer on the shift. Releasing from `NO_SHOW` clears `guard_id` and `pay_rate_cents_per_hour`, and because the officer's `no_show_count` is recomputed from the shifts that *currently* stand in `NO_SHOW`, releasing the shift also lifts the strike from the officer's record.

Cancellation is the `Scheduler`'s other exit. The `CANCEL` action carries a shift from `OPEN_UNFILLED`, `SCHEDULED` or `CONFIRMED` to the terminal `CANCELLED`, with no precondition beyond the state itself. Cancelling from `OPEN_UNFILLED` recomputes the site's `coverage_status` — a cancelled shift is no longer an uncovered gap. Cancelling from `SCHEDULED` also clears `guard_id` and `pay_rate_cents_per_hour` and recomputes the officer's `committed_hours` alongside the site's coverage. Cancelling from `CONFIRMED` clears `guard_id`, `pay_rate_cents_per_hour` and the briefing pin, and likewise recomputes `committed_hours` and `coverage_status`.

**Confirmation** carries a shift `SCHEDULED → CONFIRMED` and is the one shift action that two roles may present: a `Scheduler`, on any shift, or the assigned `Guard`, on their own shift — an officer presenting it against a shift whose `guard_id` is not their own is rejected with `ERR_NOT_SHIFT_OWNER`. The shift must have an assigned officer (`ERR_SHIFT_NOT_ASSIGNED`), that officer's employment dimension must still read `ACTIVE` (`ERR_GUARD_NOT_ACTIVE`), their licensing dimension must still read `LICENSED` (`ERR_GUARD_NOT_LICENSED`), and they must still hold a verified, unexpired certification for every code in the post's `required_cert_codes` (`ERR_GUARD_CERT_MISSING`). The eligibility gates are re-run at confirmation because time has passed since assignment and a licence may have lapsed in the interval. One further gate applies here and nowhere else: the shift's post must have exactly one post order sitting in `PUBLISHED`, or the confirmation is rejected with `ERR_POST_ORDER_NOT_PUBLISHED` — an officer may not confirm onto a post that has never told them what the job is. On success, the shift pins `pinned_post_order_id` to that published document's `id` and `pinned_post_order_version` to that document's `version`, freezing the briefing as described in §3.2.

### 3.6. On Duty: Clock-In, the NFC Tour, and Clock-Out

Only the assigned officer may clock in, and only from `CONFIRMED`; the transition is `CONFIRMED → IN_PROGRESS`. The officer's identity is checked against the shift's `guard_id` (`ERR_NOT_SHIFT_OWNER`), their employment dimension must read `ACTIVE` (`ERR_GUARD_NOT_ACTIVE`) and their licensing dimension `LICENSED` (`ERR_GUARD_NOT_LICENSED`) — a compliance sweep between confirmation and the start of the shift can still catch a lapsed licence at the door. Clocking in stamps `actual_clock_in_at` from the logical clock. It then recomputes the officer's `late_clock_in_count`, which counts their shifts whose `actual_clock_in_at` exceeds `scheduled_start_at` by more than five minutes — a five-minute grace, so arriving at exactly five minutes past is on time and six minutes past is not — and, because a count that feeds the reliability score has changed, it recomputes both of the officer's reliability scores. If the recomputed provisional score has fallen below the suspension threshold while the officer is still `ACTIVE`, the officer is automatically suspended, with all the consequences §3.8 describes.

**Tour scans** are how the officer proves they walked the ground. During an `IN_PROGRESS` shift, the assigned officer taps an NFC tag and records the tap by submitting its `checkpoint_tag_uid`. The scan is admissible only against a shift that is `IN_PROGRESS` — a tap against a shift in any other status is rejected with `ERR_INVALID_STATE` — and only by the officer to whom the shift belongs (`ERR_NOT_SHIFT_OWNER`). The submitted `checkpoint_tag_uid` must be a member of the post's `checkpoint_tag_uids`; a tag the post does not know is rejected with `ERR_UNKNOWN_CHECKPOINT_TAG` (HTTP 422). A recorded scan carries the `shift_id` it belongs to, its `checkpoint_tag_uid`, a `scanned_at` instant stamped from the logical clock, and an `is_duplicate` flag which is set true when this shift already had a scan for the same tag. Duplicates are stored and returned — the audit trail keeps them — but they contribute nothing to coverage: what matters is the set of *distinct* tags touched. Scans may be listed with optional `shift_id` and `checkpoint_tag_uid` filters.

**Clock-out** carries the shift `IN_PROGRESS → COMPLETED` and is again restricted to the shift's own officer (`ERR_NOT_SHIFT_OWNER`). It is by far the heaviest operation in the system, because it is the moment the shift's money is reckoned. It stamps `actual_clock_out_at` from the logical clock and then computes, in this order:

First, **tour compliance**. Let the total be the number of entries in the post's `checkpoint_tag_uids`. If that total is zero — the post has no tour — then `tour_compliance_pct` is 100.0 by convention, and the shift contributed no missed checkpoints; a post with nothing to walk is fully compliant by definition. Otherwise, count the distinct `checkpoint_tag_uid` values across the tour scans recorded on this shift; `tour_compliance_pct` is one hundred multiplied by that distinct count, divided by the total, rounded half up to two decimal places, and the number of checkpoints this shift missed is the total less the distinct count.

Second, the **final billable amount**. Take the raw worked interval — the difference between `actual_clock_out_at` and `actual_clock_in_at` in hours, less `planned_break_minutes` divided by 60. Round that raw figure **up** to the next whole quarter hour: divide by 0.25, take the ceiling, multiply back by 0.25. Cap the result at the shift's `scheduled_hours` plus half an hour of overrun grace — the client is never billed for more than thirty minutes beyond the scheduled length, however long the officer stayed — and round the capped figure half up to two decimal places. That is `billable_hours`. Multiply it by the shift's snapshotted `bill_rate_cents_per_hour` and round half up to a whole cent to obtain the base charge. Now apply the service-level credit: if the shift's `tour_compliance_pct` is strictly below the post's `tour_compliance_floor_pct`, then `sla_credit_cents` is ten percent of that base charge, rounded half up to a whole cent; if compliance is at or above the floor, `sla_credit_cents` is zero. Finally, `final_billable_cents` is the base charge less `sla_credit_cents`. Note the rounding order once more: the hours are rounded to two decimals *before* they meet the rate, never after.

Third, the officer's **pay for the week**, computed by the weekly sweep described immediately below, which sets this shift's `paid_hours`, `overtime_hours` and `pay_cents`.

Fourth, the shift's `margin_cents`, which is simply its `final_billable_cents` less its `pay_cents`.

Clocking out also recomputes the officer's `missed_checkpoint_count` — the sum, across their shifts, of the post's checkpoint count less the distinct tags scanned on that shift — recomputes both reliability scores, and recomputes `committed_hours`, since a completed shift has left the committed set.

**The weekly pay sweep.** Pay cannot be computed shift by shift in isolation, because overtime depends on what the officer has already worked that week. The sweep therefore recalculates the officer's entire ISO week. The week runs from Monday at 00:00:00Z inclusive to the following Monday at 00:00:00Z exclusive, and a shift is placed in a week by its `scheduled_start_at` — never by when the officer actually clocked in. The input set is the officer's shifts in that week whose status is `COMPLETED` or `VERIFIED`; shifts that are `IN_PROGRESS`, `NO_SHOW`, `CANCELLED`, `SCHEDULED` or `OPEN_UNFILLED` are excluded entirely. Those shifts are processed strictly in chronological order — ascending `scheduled_start_at`, ties broken by ascending `created_at` — with a running accumulator of the hours already paid earlier in the week, which begins the week at zero.

For each shift in that order:

- Its `paid_hours` is the raw worked interval — the difference between `actual_clock_out_at` and `actual_clock_in_at` in hours, less `planned_break_minutes` divided by 60 — rounded to the **nearest** quarter hour, half up. (This is where pay and billing diverge: billing ceils, pay rounds to nearest.)
- Its effective hourly rate depends on the **night window**. Take the UTC hour component of the shift's `scheduled_start_at`. If that hour is 22 or later, or is earlier than 6, the shift is a night shift and its effective rate is the shift's snapshotted `pay_rate_cents_per_hour` multiplied by 1.10, rounded half up to a whole cent *before* it is used for anything else. Otherwise the effective rate is the snapshotted rate unchanged. A ten percent night differential, in other words, and the window is keyed on the scheduled start hour, not on when the officer actually turned up.
- Its regular portion is the smaller of its own `paid_hours` and the hours still remaining before the officer reaches 40.00 hours for the week — that is, 40.00 less the running accumulator — floored at zero so that an officer already past 40.00 hours accrues no further regular time. Its `overtime_hours` is its `paid_hours` less that regular portion, rounded half up to two decimal places. A shift that straddles the 40.00-hour line therefore splits, part regular and part overtime. The threshold is strict: regular hours are consumed only while the accumulator sits strictly below 40.00.
- Its `pay_cents` is the regular portion multiplied by the effective rate, rounded half up to a whole cent, plus the `overtime_hours` multiplied by the effective rate and by the overtime multiplier of 1.5, rounded half up to a whole cent. The two products are rounded separately and then added; the night differential and the overtime premium compound, so an overtime hour on a night shift is paid at 1.10 times the base rate, rounded to whole cents, then multiplied by 1.5.
- The running accumulator then grows by this shift's `paid_hours`, and the week's total pay grows by this shift's `pay_cents` — each shift rounded first, then summed, never the other way around.

The same sweep backs a read-only **payroll summary** for an officer: given a `week_start` naming the Monday of the desired ISO week, it recomputes the week and reports `guard_id`, `week_start`, `shift_count`, `total_paid_hours`, `regular_hours`, `overtime_hours` and `weekly_pay_cents`.

**Verification** is a `FieldSupervisor`'s sign-off that a completed shift is fit to bill, carrying it `COMPLETED → VERIFIED`. It requires only that the shift's `actual_clock_out_at` be set. On success the shift's `verified_at` is stamped from the logical clock, the officer's confirmed reliability score is recomputed — the shift has now entered the confirmed input set — and the shift becomes eligible to be carried onto a client invoice. `VERIFIED` is terminal for the shift.

### 3.7. No-Shows, Reliability and Automatic Suspension

When an officer does not turn up, a `FieldSupervisor` declares a **no-show**, carrying the shift from `SCHEDULED` or from `CONFIRMED` to `NO_SHOW`. Two preconditions apply. The shift must have an assigned officer, or the declaration is rejected with `ERR_SHIFT_NOT_ASSIGNED`. And the grace period must have elapsed: the current logical clock must be at or after the shift's `scheduled_start_at` plus fifteen minutes. A declaration made before that instant is rejected with `ERR_INVALID_STATE` — a supervisor may not write off an officer who is merely running late. Declaring a no-show against a shift that was `CONFIRMED` additionally clears `pinned_post_order_id` and `pinned_post_order_version`; otherwise the two declarations behave identically.

Declaring a no-show sets off the longest cascade in the system, and every hop of it matters:

1. The officer's `no_show_count` is recomputed — a count of their shifts that currently stand in `NO_SHOW`, which this shift has just joined.
2. Because that count feeds the reliability model, both of the officer's reliability scores are recomputed.
3. If the recomputed provisional score has fallen below 50 while the officer's employment dimension still reads `ACTIVE`, the officer is automatically suspended: `ACTIVE → SUSPENDED`, exactly as if a `ComplianceOfficer` had presented the suspend action.
4. That suspension releases every *other* shift of the officer whose status is `SCHEDULED` or `CONFIRMED` and whose `scheduled_start_at` is at or after the current logical clock, returning each to `OPEN_UNFILLED` with `guard_id`, `pay_rate_cents_per_hour`, `pinned_post_order_id` and `pinned_post_order_version` cleared, and recomputing the officer's `committed_hours`.
5. Each released shift forces a recompute of `Site.coverage_status` on its site, and a site flips to `AT_RISK` whenever a released shift begins within 48 hours of the current clock.

The no-show shift itself also leaves the committed set, so `committed_hours` is recomputed for it too. One no-show at a badly staffed site can therefore leave three sites `AT_RISK` and an officer suspended, all from a single supervisor action — which is precisely the operational reality the system is meant to make visible.

**The reliability model.** Every officer carries two scores, both bounded between 0.0 and 100.0 and both rounded half up to two decimal places. The arithmetic is identical for both; only the input set differs.

Start from a perfect 100. Compute the officer's *effective* no-shows as their `no_show_count` less their `strike_waiver_count`, floored at zero. Deduct 30 points for each effective no-show. Deduct 5 points for each entry in `late_clock_in_count`. Deduct 2 points for each entry in `missed_checkpoint_count`. Clamp the result to the range 0.0 to 100.0 and round it half up to two decimals.

`reliability_score` — the **provisional** score — draws its three counts from the officer's shifts whose status is `IN_PROGRESS`, `COMPLETED`, `VERIFIED` or `NO_SHOW`. This is the score that drives the auto-suspension gate: whenever it is recomputed, if it is strictly below 50 and the officer's employment dimension reads `ACTIVE`, the officer is suspended. The boundary is strict — a score of exactly 50.00 does *not* suspend.

`verified_reliability_score` — the **confirmed** score — draws its counts only from shifts whose status is `VERIFIED` or `NO_SHOW`. It ignores completed-but-unverified and in-progress work entirely, so an officer who missed checkpoints on a shift that a supervisor has not yet signed off carries a strictly higher confirmed score than provisional score. The confirmed score is for reporting only. It never suspends anyone.

Both scores default to 100.0 on a fresh guard record, and both are recomputed on clock-in, on clock-out, on a no-show declaration, on shift verification and on reinstatement.

`strike_waiver_count` is the amnesty mechanism. When a `ComplianceOfficer` reinstates a suspended officer, the system snapshots the officer's current `no_show_count` into `strike_waiver_count` and recomputes both scores. Because effective no-shows are the count *less* the waiver, every no-show accrued up to that moment is forgiven, the deduction vanishes, and the score lifts back above the suspension threshold — which is what makes the reinstatement stick rather than immediately re-suspending the officer. Fresh no-shows after reinstatement are not covered by the waiver and count against the officer as usual.

Suspension and termination share the same schedule-release behaviour. Whether triggered by a `ComplianceOfficer` presenting the suspend or terminate action, or by the automatic suspension gate, every shift of the officer sitting in `SCHEDULED` or `CONFIRMED` whose `scheduled_start_at` is at or after the current logical clock returns to `OPEN_UNFILLED` with `guard_id`, `pay_rate_cents_per_hour` and the briefing pin cleared; the officer's `committed_hours` is recomputed; and `Site.coverage_status` is recomputed for every site a released shift touched. Shifts already under way, and shifts in the past, are left alone.

### 3.8. Incident Reporting, Escalation and Closure

An officer who witnesses something on post files an **incident report** naming the `shift_id` it occurred on, a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`, and a non-empty `narrative` giving their written account. The report is created in `DRAFT`, one of seven statuses — `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `ESCALATED`, `RESOLVED` and the terminal `CLOSED`. Its `escalation_level` starts at 0 and its `escalated_by_user_id`, `resolution_note` and `closed_by_user_id` all start null. Only the officer to whom the referenced shift belongs may file it (`ERR_NOT_SHIFT_OWNER`). Incidents may be listed with optional `shift_id` and `status` filters.

Submission is the officer's own action, carrying the report `DRAFT → SUBMITTED`. It requires that the acting officer own the incident's shift (`ERR_NOT_SHIFT_OWNER`) and that the referenced shift sit in `IN_PROGRESS`, `COMPLETED` or `VERIFIED` — an incident cannot be submitted against a shift that has not yet begun, and the attempt is rejected with `ERR_INVALID_STATE`.

From there the report belongs to the `FieldSupervisor`. Review carries it `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW`, a supervisor has three onward moves. They may request more information, carrying it `UNDER_REVIEW → INFO_REQUESTED`, from which the owning officer submits again — `INFO_REQUESTED → SUBMITTED`, still subject to the ownership check — and the review cycle repeats. They may escalate, carrying it `UNDER_REVIEW → ESCALATED`, which is admissible **only** when the report's `severity` is `HIGH` or `CRITICAL`; escalating a `LOW` or `MEDIUM` incident is rejected with `ERR_INVALID_STATE`. Escalation increments `escalation_level` by one and records the escalating supervisor's `X-User-ID` into `escalated_by_user_id`. Or they may resolve it directly, carrying it `UNDER_REVIEW → RESOLVED`.

An escalated report is not stranded. A supervisor may pull it back into review, `ESCALATED → UNDER_REVIEW`, and from there escalate it a second time — each escalation lifting `escalation_level` by one further and overwriting `escalated_by_user_id` with the most recent escalating operator. An escalated report may also be resolved directly, `ESCALATED → RESOLVED`.

Resolution, from either `UNDER_REVIEW` or `ESCALATED`, requires a `note` in the payload — a non-empty string, or the request is rejected with `ERR_VALIDATION` — and stores it as the report's `resolution_note`.

Closure carries the report `RESOLVED → CLOSED` and stamps `closed_by_user_id` with the acting supervisor's `X-User-ID`. This is where segregation of duties bites, exactly as §2.10 states: if the report's `escalated_by_user_id` is not null, the closing supervisor's `X-User-ID` must differ from it, or the close is rejected with `ERR_SEGREGATION_OF_DUTIES`. A report that was never escalated has a null `escalated_by_user_id` and may be closed by anyone holding the supervisor role, including the one who resolved it.

### 3.9. Invoicing the Client: Lines, Credits and the Margin Floor

An `AccountManager` opens a **draft invoice** for a client by naming the `client_id` and the billing window's `period_start` and `period_end`. The window is half-open — the start inclusive, the end exclusive — and `period_end` must be strictly later than `period_start`, or the request is rejected with `ERR_VALIDATION`.

Opening the invoice generates its lines. The eligible population is the coverage shifts whose status is `VERIFIED`, whose post belongs to a site of this client, whose `scheduled_start_at` falls at or after `period_start` and strictly before `period_end`, and which are not already carried by an invoice line on some other invoice whose status is anything other than `VOID`. A voided invoice releases its shifts back into the eligible pool; a live one holds them. Lines are created in ascending `scheduled_start_at` order, ties broken by ascending `created_at`.

Each **invoice line** carries the `invoice_id` it belongs to and the `shift_id` it bills, together with four figures copied from that shift at the moment the line was generated: `hours`, copied from the shift's `billable_hours`; `rate_cents_per_hour`, copied from the shift's `bill_rate_cents_per_hour`; `gross_amount_cents`, copied from the shift's `final_billable_cents` — which already has any service credit deducted from it; and `pay_cost_cents`, copied from the shift's `pay_cents`, which exists to compute margin and is never billed to anyone. A line also carries `credit_cents`, the cumulative credits applied to it, which starts at 0, and `amount_cents`, which is always the line's `gross_amount_cents` less its `credit_cents`. Invoice lines may be listed with optional `invoice_id` and `shift_id` filters.

**Invoice totalling** runs whenever the invoice is opened, issued or credited, and its evaluation order is pinned. First, each line's `amount_cents` is set to its `gross_amount_cents` less its `credit_cents`; no rounding occurs at line level, because every figure involved is already a whole number of cents. Second, `subtotal_cents` is the sum of `amount_cents` across the invoice's lines. Third — and this is the step to get right — the administrative fee percentage is selected from a tier keyed on `subtotal_cents`, **never** on `total_cents`: a subtotal strictly below 150000 cents takes an `admin_fee_pct` of 8.0; a subtotal from 150000 cents up to but not including 500000 cents takes 5.0; a subtotal of 500000 cents or more takes 3.0. Fourth, `admin_fee_cents` is `subtotal_cents` multiplied by `admin_fee_pct`, divided by one hundred, and rounded half up to a whole cent — rounded exactly once. Fifth, `total_cents` is `subtotal_cents` plus `admin_fee_cents`. Sixth, `pay_cost_cents` on the invoice is the sum of `pay_cost_cents` across its lines, and `margin_pct` is one hundred multiplied by the difference between `subtotal_cents` and `pay_cost_cents`, divided by `subtotal_cents`, rounded half up to two decimal places; when `subtotal_cents` is zero, `margin_pct` is 0.0 rather than undefined.

The tiering has a counter-intuitive consequence worth stating explicitly, because it is not a bug: the tiers *descend* as the subtotal grows. A credit that pushes a subtotal down across a tier boundary — from 500000 cents or more to something below it, say — moves the invoice into a *higher* fee percentage, and can therefore **raise** `admin_fee_cents` while lowering `total_cents`. The fee is keyed on the subtotal because keying it on the total would be circular, and the tier lookup on `subtotal_cents` is the resolution of that circularity.

An invoice moves through six statuses — `DRAFT`, `ISSUED`, `DISPUTED`, `ADJUSTED`, `PAID` and `VOID` — of which `PAID` and `VOID` are terminal, and every transition is an `AccountManager` action.

**Issuing** carries a `DRAFT` invoice to `ISSUED`. Two gates guard it. The invoice must carry at least one line, or the request is rejected with `ERR_INVOICE_NO_BILLABLE_SHIFTS` — there is nothing to bill. And the invoice's `margin_pct` must be at or above the client's `margin_floor_pct`, or the request is rejected with `ERR_MARGIN_BELOW_FLOOR`. The floor comparison is inclusive: a margin exactly equal to the floor passes; a margin strictly below it does not. Issuing recomputes the invoice's totals, stamps `issued_at` from the logical clock, and recomputes the client's `outstanding_balance_cents` and `paid_to_date_cents`.

**Disputing** carries an `ISSUED` invoice to `DISPUTED` and requires a non-empty `dispute_reason` in the payload, which is stored on the invoice; an empty or missing reason is rejected with `ERR_VALIDATION`. A disputed invoice is still owed, so it continues to count toward the client's `outstanding_balance_cents`.

**Crediting** carries a `DISPUTED` invoice to `ADJUSTED` and is how a dispute is settled without voiding the whole document. The payload names the `line_id` to be credited and the `credit_cents` to apply. The line must belong to this invoice — a line from another invoice, or an identifier that resolves to nothing, is rejected with `ERR_INVOICE_LINE_NOT_FOUND` — and the credit must be at least 1 cent and at most the line's current `amount_cents`, or the request is rejected with `ERR_CREDIT_EXCEEDS_LINE`. Crediting runs a three-hop cascade: the credit amount is added to the line's `credit_cents` and the line's `amount_cents` is re-derived as `gross_amount_cents` less the new `credit_cents`; the changed line amount forces a full re-run of invoice totalling, which re-derives `subtotal_cents`, **re-selects** `admin_fee_pct` from the new subtotal's tier, and recomputes `admin_fee_cents`, `total_cents` and `margin_pct`; and the changed `total_cents` forces a recompute of the client's `outstanding_balance_cents`. Multiple credits may be applied — `credit_cents` on a line is cumulative — and each one re-runs the whole cascade.

An `ADJUSTED` invoice may be **re-issued**, carrying it back to `ISSUED` under exactly the same two gates as the original issuance: at least one line, and `margin_pct` at or above the client's `margin_floor_pct`. This is the cycle the dispute workflow rests on — issued, disputed, adjusted, issued again — and the margin floor is checked afresh each time round, which matters because a credit that shrinks the subtotal also shrinks the margin against an unchanged payroll cost, and can drop an invoice below a floor it previously cleared.

**Paying** carries an `ISSUED` invoice to the terminal `PAID` with no further precondition. It recomputes the client's balances: the invoice drops out of `outstanding_balance_cents` and its `total_cents` joins `paid_to_date_cents`.

**Voiding** carries an invoice to the terminal `VOID` from `DRAFT`, from `ISSUED`, from `DISPUTED` or from `ADJUSTED`, with no precondition in any case. In every case it recomputes the client's `outstanding_balance_cents` and `paid_to_date_cents` and releases the invoice's shifts back into the eligible pool for a future invoice. Voiding an issued invoice is the exact compensating half of issuing it: the client's balances return to precisely the values they held before the issuance. Invoices may be listed with optional `client_id` and `status` filters.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — driving a lifecycle action, assigning a guard, clocking in or out, publishing a document, verifying a credential, running a sweep, setting the clock — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a contracting client | AccountManager |
| GET | `/clients/{id}` | Read a client, including its derived ledger fields | AccountManager, PlatformAdmin |
| POST | `/sites` | Create a guarded site under a client | AccountManager |
| GET | `/sites` | List sites, optionally filtered by client and coverage status | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, PlatformAdmin |
| GET | `/sites/{id}` | Read one site, including its derived coverage status | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, Guard, PlatformAdmin |
| POST | `/posts` | Create a guard post at a site | AccountManager |
| GET | `/posts` | List posts, optionally filtered by site | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, PlatformAdmin |
| GET | `/posts/{id}` | Read one guard post | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, Guard, PlatformAdmin |
| POST | `/post-orders` | Draft a post-order revision for a post | AccountManager |
| POST | `/post-orders/{id}/publish` | Publish a drafted post order | AccountManager |
| GET | `/post-orders` | List post orders, optionally filtered by post and status | AccountManager, Scheduler, FieldSupervisor, Guard, PlatformAdmin |
| GET | `/post-orders/{id}` | Read one post-order document | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, Guard, PlatformAdmin |
| POST | `/guards` | Create a guard record | ComplianceOfficer |
| GET | `/guards/{id}` | Read a guard, including both state dimensions and both reliability scores | ComplianceOfficer, Scheduler, FieldSupervisor, AccountManager, Guard, PlatformAdmin |
| POST | `/guards/{id}/status` | Drive the guard's employment dimension | ComplianceOfficer |
| GET | `/guards/{id}/payroll-summary` | Recompute and return the guard's weekly payroll | ComplianceOfficer, Scheduler, AccountManager, PlatformAdmin |
| POST | `/credentials` | Record a guard licence or training certification | ComplianceOfficer |
| POST | `/credentials/{id}/verify` | Verify a pending credential | ComplianceOfficer |
| GET | `/credentials` | List credentials, optionally filtered by guard, kind and status | ComplianceOfficer, Scheduler, FieldSupervisor, PlatformAdmin |
| GET | `/credentials/{id}` | Read one credential | ComplianceOfficer, Scheduler, FieldSupervisor, PlatformAdmin |
| POST | `/compliance-sweeps` | Run the licensing/certification expiry sweep | ComplianceOfficer |
| POST | `/shifts` | Create a coverage shift on a post | Scheduler |
| POST | `/shifts/{id}/assignments` | Assign or reassign a guard to a shift | Scheduler |
| POST | `/shifts/{id}/actions` | Drive the shift lifecycle | Scheduler, FieldSupervisor, Guard |
| POST | `/shifts/{id}/clock-in` | Guard clocks in | Guard |
| POST | `/shifts/{id}/clock-out` | Guard clocks out; computes billing, pay and margin | Guard |
| POST | `/shifts/{id}/scans` | Record an NFC checkpoint tap during an in-progress shift | Guard |
| GET | `/shifts` | List coverage shifts with filters | Scheduler, FieldSupervisor, AccountManager, ComplianceOfficer, Guard, PlatformAdmin |
| GET | `/shifts/{id}` | Read one coverage shift with all computed fields | AccountManager, Scheduler, FieldSupervisor, ComplianceOfficer, Guard, PlatformAdmin |
| GET | `/scans` | List NFC tour scans, optionally filtered by shift and tag | Scheduler, FieldSupervisor, AccountManager, Guard, PlatformAdmin |
| GET | `/scans/{id}` | Read one NFC tour scan | Scheduler, FieldSupervisor, AccountManager, Guard, PlatformAdmin |
| POST | `/incidents` | File an incident report against a shift | Guard |
| POST | `/incidents/{id}/actions` | Drive the incident lifecycle | Guard, FieldSupervisor |
| GET | `/incidents` | List incident reports, optionally filtered by shift and status | Guard, FieldSupervisor, AccountManager, PlatformAdmin |
| GET | `/incidents/{id}` | Read one incident report | Guard, FieldSupervisor, AccountManager, PlatformAdmin |
| POST | `/invoices` | Open a draft invoice for a client and generate its lines | AccountManager |
| POST | `/invoices/{id}/actions` | Drive the invoice lifecycle | AccountManager |
| GET | `/invoices` | List invoices, optionally filtered by client and status | AccountManager, PlatformAdmin |
| GET | `/invoices/{id}` | Read one invoice | AccountManager, PlatformAdmin |
| GET | `/invoice-lines` | List invoice lines, optionally filtered by invoice and shift | AccountManager, PlatformAdmin |
| GET | `/invoice-lines/{id}` | Read one invoice line | AccountManager, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_POST_NOT_FOUND` | 404 |
| `ERR_POST_ORDER_NOT_FOUND` | 404 |
| `ERR_GUARD_NOT_FOUND` | 404 |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVOICE_LINE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SHIFT_NOT_ASSIGNED` | 409 |
| `ERR_GUARD_NOT_ACTIVE` | 409 |
| `ERR_GUARD_NOT_LICENSED` | 409 |
| `ERR_GUARD_CERT_MISSING` | 409 |
| `ERR_POST_ORDER_NOT_PUBLISHED` | 409 |
| `ERR_GUARD_DOUBLE_BOOKED` | 409 |
| `ERR_GUARD_REST_PERIOD_VIOLATION` | 409 |
| `ERR_POST_CAPACITY_EXCEEDED` | 409 |
| `ERR_NOT_SHIFT_OWNER` | 403 |
| `ERR_UNKNOWN_CHECKPOINT_TAG` | 422 |
| `ERR_DUPLICATE_EMPLOYEE_CODE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVOICE_NO_BILLABLE_SHIFTS` | 422 |
| `ERR_CREDIT_EXCEEDS_LINE` | 422 |
| `ERR_MARGIN_BELOW_FLOOR` | 422 |
