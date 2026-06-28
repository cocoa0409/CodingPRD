# Alcohol Beverage Control API — Product Requirements Document

## 1. Introduction

The Alcohol Beverage Control (ABC) API is the system of record for a state liquor authority that licenses, polices, and taxes every business permitted to manufacture, distribute, or sell alcoholic beverages. The authority issues licenses against a finite, population-derived quota; vets every applicant through background and zoning review; entertains public protests and adjudicates them at formal hearings; disciplines licensees through violations, fines, suspensions and revocations; and collects tiered excise reporting across the classic three-tier supplier/wholesaler/retailer distribution chain. Each of these activities is governed by statutory deadlines, separation-of-duties rules between the staff who recommend and the staff who decide, and a fee ledger that must never be circumvented.

This document specifies the API a single back-office implementation must expose. It is written so that the workflow narrative — who may act, in what order, under which preconditions, and with what downstream consequences — is unambiguous to an engineer who has never seen the underlying data model. The domain is deliberately stateful: an application threads through draft, submission, examiner review, a public protest window, an optional hearing branch, approval and issuance; a license then cycles through renewal terms, may be suspended and reinstated, and can be revoked or allowed to expire. Money, quota slots, demerit points, and server-permit capacity all move as side effects of these transitions, and every such movement is described in Section 3. Section 2 fixes the cross-cutting contracts — authentication, response envelope, pagination, concurrency, precision, and the consistency rules that bind parents to children — that every endpoint obeys.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the public protest-filing endpoint must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they act. When either header is missing, or when the supplied role is not one the system recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is filing a protest, which the public may do anonymously; all other operations demand a recognised role.

The system recognises seven roles, spelled exactly: `Director`, `LicensingExaminer`, `ZoningOfficer`, `AdjudicationOfficer`, `Investigator`, `Applicant`, and `Anonymous`. The `Director` is the senior authority who approves, issues and denies applications, reinstates licenses, withdraws protests, approves and rejects transfers, revokes server permits, and manages configuration data. The `LicensingExaminer` processes applications — beginning review, opening the protest period, and resolving background checks — and may run the scheduled clock re-evaluations. The `ZoningOfficer` decides zoning reviews and nothing else. The `AdjudicationOfficer` conducts protest hearings and adjudicates violations and their administrative actions. The `Investigator` files violations. The `Applicant` is the licensee business itself: it creates and submits applications, pays fees, manages server permits, renews licenses, contests violations, files compliance reports, and requests transfers. `Anonymous` denotes an unauthenticated public party who may only file a protest. When an authenticated role is recognised but is not permitted to perform the requested operation per the access matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Most roles carry an **opaque identity**: when `X-User-Role` is `Director`, `LicensingExaminer`, `ZoningOfficer`, `AdjudicationOfficer`, `Investigator`, or `Anonymous`, the `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records it where a transition demands an actor footprint — for example as `examiner_user_id` on a `LicenseApplication` when an examiner begins review, as `officer_user_id` on a `Hearing` when an officer renders an outcome, as `investigator_user_id` on a `Violation` when it is filed, and as `adjudicator_user_id` on an `AdministrativeAction` when a violation is sustained — but it never compares that identifier to any entity's `id`. The `Applicant` role is different: it is **entity-backed**. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`. Ownership checks on any resource that references an `Applicant` compare the resource's applicant foreign key to `X-User-ID`.

The opaque actor footprints exist to support **separation of duties**, the system's core integrity discipline. The `X-User-ID` that records a recommendation must differ from the `X-User-ID` that records the corresponding decision, and the `X-User-ID` that files a violation must differ from the one that adjudicates it. The precise pairings are described in Section 3 alongside the workflows they guard; whenever such a check fails the response is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, every list is returned sorted by the `created_at` timestamp in ascending order.

Each list response surfaces four pagination fields in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`. `total_count` reflects the full size of the filtered collection before the page window is applied, and `has_more` is true when items remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable and therefore also carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by exactly one with each mutation. There are no immutable, version-less entities here; `updated_at` and `version` are present on every resource the API returns.

Time in this system is **logical, not wall-clock**. A single server-wide clock governs every deadline, window, and expiry — protest periods, renewal windows, permit expiry, hearing windows, term boundaries. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until an explicit clock-set call is made it stays at that default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied instant; the request supplies the target instant as `to_iso8601` and the response echoes the new value as `now`. Advancing the clock does **not** by itself fire any scheduled transition: licenses do not flip to renewal-due, permits do not expire, and applications do not auto-advance merely because time passed. Those deferred transitions are realised only when the corresponding re-evaluation capability is invoked against the specific resource, as described in Section 3.

### 2.5. Hierarchical Consistency and Cascades

This is a flat resource model: there is no URL nesting beyond action sub-paths, and entities reference each other through foreign keys rather than containment. Nonetheless many operations mutate more than one entity, and the system applies every cascade **atomically within the triggering request** — there is no eventual consistency and no deferred reconciliation. When a license is suspended, revoked, or expires, the server immediately walks its attached server permits and resolves them in the same transaction. When a violation is sustained, the server creates the enforcement record, scores demerit points, syncs the fine ledger, and — if discipline crosses the suspension threshold — suspends the license and expires its pourers, all before the request returns. Every entity touched in a cascade independently has its `updated_at` refreshed and its `version` incremented by one. The exact cascade chains, and which counters move in which direction, are specified in Section 3 next to the workflows that trigger them.

When a request targets a nested path — for instance a child collection reached through a parent's identifier — the server validates path identifiers left to right and rejects the first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404), before evaluating any body or business rule. Existence of every path and body foreign key is checked this way (applicants, premises, license classes, quota regions, applications, licenses, protests, hearings, violations, and the rest); a reference to a non-existent resource always yields `ERR_NOT_FOUND`.

### 2.6. Monetary Values, Counts, and Precision

All monetary amounts in this system are integer **cents** — base fees, surcharges, quoted and paid fees, fines, gross sales, and excise are never fractional currency. Wherever a calculation introduces a percentage or a multiplier that would produce a fractional cent, the result is rounded to whole cents using the **round half up** convention (a half-cent always rounds away from zero, upward). The fee, fine, and excise calculations in Section 3 each pin the exact order in which rounding is applied relative to summation; that order is part of the contract and is stated precisely where each calculation is described. Quota caps and slot counts are pure integers, computed with floor division where a division appears. Demerit points, server counts, and renewal counts are integers that never drop below zero.

### 2.7. Optimistic Concurrency Control

Two write operations consume a finite, contended resource and therefore require optimistic concurrency control against a parent entity's `version`.

The first is **submitting a quota-managed application**, which reserves one of a region's finite quota slots and advances that region's `version`. A submit of a quota-managed application must carry `expected_region_version` holding the client's last observed `version` of the target `QuotaRegion`. If that value does not equal the region's current `version` — because another submit, or a slot release, has advanced the region since the client last read it — the submit is rejected with `ERR_STALE_REGION_VERSION` (HTTP 412). This makes contention for the last available slot deterministic: a client may not reserve a slot against a stale view of how many remain. (Applications for classes that are not quota-managed do not reserve a slot and therefore do not require this field.)

The second is **activating a server permit**, which consumes one of the license's finite capacity slots and advances the license's `version`. An activate must carry `expected_license_version` holding the client's last observed `version` of the parent `License`. If that value does not equal the license's current `version` — because another permit activation, or a disciplinary cascade that suspended the license and zeroed its server count, has advanced it since the client last read it — the activate is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412).

No other endpoint takes a version field. Toggling a region's moratorium is a configuration write that likewise advances the region `version` and accepts `expected_region_version`, but the two stale-version rejections above are the only OCC enforcement points: a mismatch on quota-reserve submit yields `ERR_STALE_REGION_VERSION`, and a mismatch on server activate yields `ERR_STALE_LICENSE_VERSION`.

### 2.8. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. Authentication comes first: a missing or unrecognised header pair fails with `ERR_UNAUTHENTICATED` (401) before anything else. Role authorisation is next, failing with `ERR_FORBIDDEN_ROLE` (403). Existence of every referenced resource is checked third, left-to-right through the path then the body, failing with `ERR_NOT_FOUND` (404). Whether the target is in a state from which the requested transition is defined is checked fourth, failing with `ERR_INVALID_STATE` (409). Separation-of-duties is evaluated fifth, failing with `ERR_SEGREGATION_OF_DUTIES` (403). Only after these gates do the domain-specific business rules of Section 3 apply — disqualification, zoning, background, protest timing and resolution, capacity, training, renewal timing, fines, demerits, quota, transfer-type integrity, and premise overlap — followed by request well-formedness (`ERR_INVALID_REQUEST`, 400) and finally the optimistic-concurrency version checks (`ERR_STALE_REGION_VERSION` / `ERR_STALE_LICENSE_VERSION`, 412). Where a business rule's relative position matters to the observable outcome, Section 3 states it explicitly next to that rule.

## 3. Business Logic & Workflows

### 3.1. Configuration: License Classes, Quota Regions, Applicants, and Premises

Before any application can exist, the `Director` seeds the configuration entities. A **license class** is created with a `code` — a unique, immutable class code matching the pattern of two or three uppercase letters, an underscore, and one to three digits, such as `ON_47` for an on-premise restaurant, `OFF_21` for an off-premise package store, or `MFR_23` for a manufacturer. Each class declares a `premise_type` of `ON_PREMISE`, `OFF_PREMISE`, or `MANUFACTURER`; a `quota_managed` boolean that defaults to true and, when true, caps issuance by population quota (manufacturer classes are typically not quota-managed); a `base_fee_cents` annual base fee of zero or more; a `renewal_cycle_months` term length that must be 12, 24, or 36; a `requires_zoning` boolean defaulting to true (on- and off-premise classes require zoning, manufacturers do not); and a `max_servers_per_license` count of zero or more capping how many active server permits one license of that class may carry (zero for off-premise and manufacturer classes, which do not pour).

A **quota region** is a county-level area created with a unique, immutable `region_code` such as `CTY_LA`, a census `population` of zero or more, a `persons_per_license` divisor of at least one that yields one quota slot per that many persons, and a `moratorium` boolean defaulting to false. While a region's `moratorium` is true, no new quota-managed application may be submitted there regardless of available slots. The `Director` may flip the moratorium later; that toggle sets `moratorium`, advances the region's `version`, and — as described under concurrency — accepts `expected_region_version`.

An **applicant** is registered with a non-empty `legal_name` and a self-declared `felony_flag` defaulting to false, which feeds the background-check simulation. An applicant also carries a system-managed `disqualified` flag, false at registration, which is set true automatically when any of the applicant's background checks fails; once disqualified, the applicant may not submit further applications. A **premise** is registered for an applicant in a region: it carries `applicant_id` identifying its owner, `region_code` placing it in a quota region, a non-empty `street_address`, a `distance_to_school_m` distance in metres (zero or more) to the nearest school or place of worship that the zoning buffer rule consults, and a `zoning_district` that is one of `COMMERCIAL`, `MIXED_USE`, `RESIDENTIAL`, or `INDUSTRIAL`.

### 3.2. Filing and Submitting an Application

The `Applicant` (or staff acting on their behalf) opens a **license application** by naming the `applicant_id` who is applying, the `premise_id` where the license would operate, and the `license_class_code` of the class requested. A freshly created application sits in `DRAFT` with no fee, no checks, and no quota reservation. Its lifecycle state is held in a `status` field — every stateful resource in this system (applications, background checks, zoning reviews, protests, hearings, licenses, server permits, violations, transfer requests) exposes the same `status` field, and list endpoints accept a matching `status` filter. While in `DRAFT` it may be abandoned, transitioning straight to `WITHDRAWN`.

Submitting an application advances it from `DRAFT` to `SUBMITTED` and is the system's busiest moment. It is permitted only when the owning applicant is not flagged `disqualified` (otherwise `ERR_APPLICANT_DISQUALIFIED`, 422); and, for a quota-managed class, only when the region is not under moratorium and at least one quota slot remains available (otherwise `ERR_QUOTA_EXHAUSTED`, 422). For a quota-managed class the submit must also carry `expected_region_version` and pass the stale-version check of Section 2.7. On success the server stamps `submitted_at` to the current clock instant and sets `protest_period_ends_at` to thirty days after `submitted_at` — the instant after which no further protest may be filed. It runs the fee assessment and freezes the result into `fee_quoted_cents`. It synthesises a background check in `PENDING` and records its identifier on the application as `background_check_id`. If the class requires zoning, it synthesises a zoning review in `PENDING`, computes that review's buffer determination, and records its identifier as `zoning_review_id`; for a non-zoning class no review is created and `zoning_review_id` stays null. For a quota-managed class it reserves a slot by setting `quota_slot_held` true and advancing the region's `version`, so that the availability count immediately reflects this application. A `SUBMITTED` application may still be withdrawn; doing so releases the reserved quota slot (clearing `quota_slot_held`) if one was held.

The **fee assessment** that freezes `fee_quoted_cents` at submission is forward-looking and built from the class's `base_fee_cents`. Two surcharges may stack additively on top of the base. A zoning surcharge of ten percent of the base applies when the class requires zoning, and zero otherwise. A manufacturer surcharge of twenty-five percent of the base applies when the class's `premise_type` is `MANUFACTURER`, and zero otherwise. The rounding order is pinned: each surcharge is computed as its percentage of the base and **rounded to whole cents independently first**, and only then are the base and the two rounded surcharges summed to give `fee_quoted_cents`. The quoted fee is not prorated for a standard new application — the applicant pays the full first term. The fee paid against the quote accumulates in `fee_paid_cents`, which starts at zero and grows as payments are recorded (each payment supplies an `amount_cents` that is added to `fee_paid_cents`).

### 3.3. Background Checks and Zoning Reviews

A **background check** belongs to its application via `application_id` and denormalises the subject's `applicant_id` from that application. It is born `PENDING` and is resolved by a `LicensingExaminer` to either `PASSED` or `FAILED`, with the decision supplied as `decision`; resolution stamps `resolved_at` to the current clock instant. A `PASS` decision is forbidden when the subject applicant's `felony_flag` is true — such a pass is rejected with `ERR_APPLICANT_DISQUALIFIED` (422). When a check is resolved to `FAILED`, the system performs a cross-entity cascade: in addition to setting `result` to `FAILED` and stamping `resolved_at`, it sets the owning `Applicant`'s `disqualified` flag to true, bumping that applicant's `version` and `updated_at`. That disqualification is what later blocks the applicant from submitting any new application.

A **zoning review** is synthesised only for classes that require zoning. It belongs to its application via `application_id`, denormalises the reviewed `premise_id`, and on creation computes `buffer_satisfied`. The buffer rule reads the required separation in metres from the requested class's `premise_type`: an `ON_PREMISE` or `OFF_PREMISE` class requires one hundred metres of separation from the nearest school or place of worship, while a `MANUFACTURER` class requires zero. The boundary is inclusive — `buffer_satisfied` is true exactly when the premise's `distance_to_school_m` is greater than or equal to the required separation, so a distance equal to the requirement satisfies it. A `ZoningOfficer` then decides the review, supplying `decision`, moving it from `PENDING` to one of three outcomes and stamping `resolved_at`. A `CLEAR` decision moves it to `CLEARED` but is only permitted when `buffer_satisfied` is true; when the buffer fails the officer must instead grant a variance or block. A `VARIANCE` decision moves it to `VARIANCE_GRANTED` but is forbidden when the premise's `zoning_district` is `RESIDENTIAL` — no variance may be granted into a residential district. A `BLOCK` decision moves it to `BLOCKED` unconditionally.

### 3.4. Examiner Review and the Protest Window

Once an application is `SUBMITTED`, a `LicensingExaminer` begins review, advancing it to `UNDER_REVIEW`. This is the recommendation step, and the examiner's `X-User-ID` is recorded as `examiner_user_id` so that separation of duties can later bar that same person from issuing. Beginning review has two gates: the application's background check must have resolved to `PASSED` — otherwise `ERR_BACKGROUND_NOT_PASSED` (422) — and, when a zoning review exists, that review's `result` must be either `CLEARED` or `VARIANCE_GRANTED` — otherwise `ERR_ZONING_NOT_CLEARED` (422); a `BLOCKED` or still-`PENDING` zoning review bars review. From `UNDER_REVIEW` the examiner opens the protest period, advancing the application to `PROTEST_PERIOD`; this is the window during which the public may file protests, and it closes at the previously stamped `protest_period_ends_at`.

A **protest** may be filed by anyone — including an anonymous member of the public — against an application named by `application_id`, citing a non-empty `protester_name` and a statutory `grounds` of `PUBLIC_NUISANCE`, `OVER_CONCENTRATION`, `ZONING`, or `MORAL_CHARACTER`. A protest is born `FILED`. Filing is allowed only while the application is in `PROTEST_PERIOD` and the current clock instant is strictly before `protest_period_ends_at`; a protest filed after the window has closed, or against an application not in `PROTEST_PERIOD`, is rejected with `ERR_PROTEST_WINDOW_CLOSED` (422). A `Director` may withdraw a protest while it is `FILED`, moving it to `WITHDRAWN`.

### 3.5. Approval, the Hearing Branch, and Issuance

After the protest window the application forks. If no protest stands in the way, a `Director` approves the application, advancing it from `PROTEST_PERIOD` to `APPROVED`. Approval has three preconditions evaluated together. First, the protest window must have fully elapsed — the current clock instant must be greater than or equal to `protest_period_ends_at`; approving early is rejected with `ERR_PROTEST_WINDOW_OPEN` (422). Second, no protest for the application may be unresolved or sustained — that is, no protest may be in `FILED`, `SCHEDULED`, or `SUSTAINED` status; otherwise `ERR_PROTEST_UNRESOLVED` (422). Third, the approving `Director`'s `X-User-ID` must differ from the application's `examiner_user_id`, since the issuer may not be the recommender; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Because these are distinct failure modes, an early approval surfaces the window error, an approval blocked by a live protest surfaces the unresolved-protest error, and a same-person approval surfaces the separation error.

The alternative branch is triggered when a protest is taken to hearing. An `AdjudicationOfficer` schedules a hearing for a protest that is `FILED` while its application is in `PROTEST_PERIOD`; this moves the protest from `FILED` to `SCHEDULED`, creates a `Hearing` in `PENDING` whose identifier is recorded on the protest as `hearing_id`, and moves the application from `PROTEST_PERIOD` to `PROTEST_HEARING` — the fork distinct from `APPROVED`. The hearing is booked into a non-empty `room_code` over a window from `starts_at` (inclusive lower bound) to `ends_at` (exclusive upper bound), where `ends_at` must be strictly after `starts_at`. The room may not be double-booked: the requested window must not overlap any existing hearing already booked in the same `room_code`. Overlap here uses **half-open** semantics — two windows that merely touch, where one ends exactly when the next begins, do **not** conflict and are allowed; any genuine overlap is rejected with `ERR_HEARING_ROOM_CONFLICT` (409).

At the hearing an `AdjudicationOfficer` renders an `outcome`, supplied on the render request, of either `PROTEST_SUSTAINED` or `PROTEST_OVERRULED`; the hearing may be rendered only once the current clock instant has reached `starts_at`, and only while its `outcome` is `PENDING`. Rendering stamps the officer's `X-User-ID` as `officer_user_id`. A `PROTEST_OVERRULED` outcome moves the hearing to `PROTEST_OVERRULED`, marks the protest `OVERRULED`, and returns the application from `PROTEST_HEARING` back to `PROTEST_PERIOD` so the `Director` may proceed to approve — the branch rejoin. A `PROTEST_SUSTAINED` outcome moves the hearing to `PROTEST_SUSTAINED`, marks the protest `SUSTAINED`, denies the application (moving it to `DENIED`), and releases any reserved quota slot, freeing the region's count by one.

Once an application is `APPROVED`, the `Director` issues it, advancing it to `ISSUED`. Issuance has two preconditions: the fee must be fully paid — `fee_paid_cents` must be greater than or equal to `fee_quoted_cents`, otherwise `ERR_FEE_UNPAID` (422) — and again the issuing `Director`'s `X-User-ID` must differ from `examiner_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). Issuance creates the **license** in `ACTIVE` status: its term starts at the current clock instant (`term_start_at`), ends at `term_start_at` plus the class's renewal-cycle months (`term_end_at`), and its renewal window opens sixty days before term end (`renewal_window_opens_at` equal to `term_end_at` minus sixty days). For a quota-managed class the reservation is converted to a committed slot — `quota_slot_held` stays true and now counts as an issued holding. The new license denormalises `application_id`, `license_class_code` and `region_code`, and starts with `renewal_count`, `demerit_points`, `active_server_count`, and `outstanding_fine_cents` all at zero.

An application may also be denied from `UNDER_REVIEW` by a `Director` (whose `X-User-ID` must differ from `examiner_user_id`), which moves it to `DENIED` and releases any held quota slot. The three terminal application states are `ISSUED`, `DENIED`, and `WITHDRAWN`.

### 3.6. Quota Allocation

Quota is the scarce good the whole licensing pipeline rations. For a given region and quota-managed class, the **cap** is the region's `population` divided by its `persons_per_license`, taking the floor (integer division). The number of slots **used** is the count of applications for that same region and class that currently hold a slot — those whose `quota_slot_held` is true, which covers applications in `SUBMITTED`, `UNDER_REVIEW`, `PROTEST_PERIOD`, `PROTEST_HEARING`, `APPROVED`, and `ISSUED`. Applications in `DRAFT`, `DENIED`, or `WITHDRAWN` do not hold a slot and are not counted. **Available** slots are the cap minus the used count. A new submit of a quota-managed application is permitted only when available is strictly greater than zero; when available equals zero the submit is blocked with `ERR_QUOTA_EXHAUSTED` (422), the same error raised when the region is under moratorium. The per-class cap, used, and available figures are also exposed as a computed read against a region, which takes the `license_class_code` of interest and returns the `region_code`, `license_class_code`, `cap`, `used`, and `available`.

### 3.7. Server Permits

A licensee staffs a pouring license with **server permits**. A permit is created in `PENDING` under a license named by `license_id`, with a non-empty `holder_name` and a `training_completed` flag (defaulting to false) recording whether the holder finished the responsible-beverage-service course. Activating a permit advances it from `PENDING` to `ACTIVE` and is gated three ways: the holder's `training_completed` must be true (otherwise `ERR_TRAINING_INCOMPLETE`, 422); the parent license must be `ACTIVE`; and the license's `active_server_count` must be strictly less than the class's `max_servers_per_license` (otherwise `ERR_SERVER_CAPACITY_EXCEEDED`, 422). Because activation consumes a finite capacity seat, it requires `expected_license_version` and is subject to the stale-license check of Section 2.7. On activation the server sets the permit's `expires_at` to thirty-six months after the current clock instant, increments the parent license's `active_server_count` by one, and advances the license's `version`. A `Director` may revoke an `ACTIVE` permit, moving it to `REVOKED` and decrementing the license's `active_server_count` by one. A permit also lapses on its own: when the clock has reached `expires_at`, a re-evaluation moves an `ACTIVE` permit to `EXPIRED` and decrements `active_server_count` (floored at zero). The terminal permit states are `EXPIRED` and `REVOKED`.

### 3.8. License Renewal and Expiry

A license runs in repeating terms. When the clock reaches `renewal_window_opens_at`, a re-evaluation flips an `ACTIVE` license to `RENEWAL_DUE` — a posture change that leaves child permit operations untouched but makes renewal actionable. From `RENEWAL_DUE` the `Applicant` renews, returning the license to `ACTIVE`. For the purposes of the state-defined gate (Section 2.8, priority 4), both `ACTIVE` and `RENEWAL_DUE` are in-bounds states for renew — the two states of the active term cycle — so only the genuinely off-cycle states `SUSPENDED`, `EXPIRED`, and `REVOKED` are undefined for renew and rejected with `ERR_INVALID_STATE` (409); an `ACTIVE` (not-yet-`RENEWAL_DUE`) license instead passes the state gate and surfaces the renewal-timing business rule below. Renewal is permitted only when the clock has reached `renewal_window_opens_at` and the license is in `RENEWAL_DUE` (otherwise `ERR_RENEWAL_WINDOW_NOT_OPEN`, 422 — this is the error raised both when an `ACTIVE` license has not yet flipped to `RENEWAL_DUE` and when a `RENEWAL_DUE` license's clock has not yet reached the window); when `outstanding_fine_cents` is zero (otherwise `ERR_OUTSTANDING_FINE`, 422); when `demerit_points` is strictly below ten (otherwise `ERR_DEMERIT_THRESHOLD`, 422); and when the renewal fee has been paid. The renewal request supplies the renewal payment as `renewal_fee_paid_cents`.

The **renewal fee** is a variant of the fee assessment. Unlike the initial quote, renewal charges the class's `base_fee_cents` only — the zoning and manufacturer surcharges are one-time charges levied at first issuance and are never re-charged on renewal. A late fee is added when the grace has lapsed: if at the moment of renewal the clock has reached `term_end_at`, a late fee equal to five percent of the base, rounded half up to whole cents, is added to the renewal charge. On a successful renewal the term rolls forward — the old `term_end_at` becomes the new `term_start_at`, the new `term_end_at` is the old `term_end_at` plus the class's renewal-cycle months, and `renewal_window_opens_at` is recomputed as the new `term_end_at` minus sixty days — and `renewal_count` increments by one. If the license is never renewed and the clock reaches `term_end_at` while it sits in `RENEWAL_DUE`, a re-evaluation expires it: the license moves from `RENEWAL_DUE` to `EXPIRED`, its attached `ACTIVE` server permits are expired, and `active_server_count` drops to zero. `REVOKED` and `EXPIRED` are the terminal license states.

### 3.9. Violations, Adjudication, and Discipline

Enforcement begins when an `Investigator` files a **violation** against a license named by `license_id`, declaring a `severity` of `MINOR`, `SERIOUS`, or `EGREGIOUS`. The filing stamps the investigator's `X-User-ID` as `investigator_user_id`; that footprint bars the same person from later adjudicating this case. A new violation is `ALLEGED`. The `Applicant` may contest it, moving it from `ALLEGED` to `CONTESTED`. An `AdjudicationOfficer` may then either dismiss a contested violation (moving `CONTESTED` to `DISMISSED`) or sustain the violation (moving `ALLEGED` or `CONTESTED` to `SUSTAINED`). Both adjudication paths require that the acting `AdjudicationOfficer`'s `X-User-ID` differ from the violation's `investigator_user_id`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). The terminal violation states are `SUSTAINED` and `DISMISSED`.

Sustaining a violation runs a multi-hop cascade. The request supplies the chosen `action_type` and, when relevant, a `suspension_days` count (zero or more, defaulting to zero). First the system creates an **administrative action** recording `violation_id`, the denormalised `license_id`, the `action_type` of `FINE`, `SUSPENSION`, or `REVOCATION`, and the adjudicator's `X-User-ID` as `adjudicator_user_id`; the action's `suspension_days` carries the supplied value, zero for a fine-only or revocation action. The system then runs the fine assessment to compute the action's `fine_cents`, which starts a paid counter `fine_paid_cents` at zero. Next it adds demerit points to the license's `demerit_points` and adds the new `fine_cents` to the license's `outstanding_fine_cents`, keeping the ledger in sync. Finally, if the license's `demerit_points` has reached ten or more, the suspension threshold fires: an `ACTIVE` or `RENEWAL_DUE` license is suspended and its attached `ACTIVE` server permits are expired with `active_server_count` driven to zero. Every entity touched in this chain — action, license, and each affected permit — has its `version` incremented and `updated_at` refreshed.

The **fine assessment** that computes `fine_cents` combines three inputs non-linearly: the violation's `severity`, the license's prior `demerit_points` taken as a snapshot *before* this violation's own points are added, and the chosen `action_type`. A severity base is selected — twenty-five thousand cents for `MINOR`, seventy-five thousand cents for `SERIOUS`, two hundred thousand cents for `EGREGIOUS`. A recidivism multiplier is then chosen from the prior `demerit_points` snapshot: a multiplier of one when the prior points are below four, one-and-one-half when the prior points are at least four and at most eight, and two when the prior points exceed eight. The raw fine is the severity base multiplied by the recidivism multiplier. Action type then adjusts it: a `REVOCATION` carries no monetary fine, so `fine_cents` is zero; a `SUSPENSION` halves the raw amount, rounded half up to whole cents, because the suspension itself is the primary penalty; and a `FINE` pays the full raw amount, rounded half up to whole cents. After rounding, a statutory cap applies: `fine_cents` is never more than five hundred thousand cents, so the rounded amount is reduced to that cap if it would exceed it.

The **demerit points** added to the license on the same sustain transition are determined by `severity` alone, independently of the fine and the action type: a `MINOR` violation adds two points, a `SERIOUS` adds four, and an `EGREGIOUS` adds six. The license's `demerit_points` never falls below zero.

Fines are paid down against the license: a fine payment supplies the `action_id` of the administrative action and an `amount_cents`, adding that amount to the action's `fine_paid_cents` and subtracting it from the license's `outstanding_fine_cents`, floored at zero.

### 3.10. Enforcing Suspension and Revocation

Some administrative actions must be explicitly enforced to take effect on the license; a fine-only action needs no enforcement beyond the ledger sync already performed at sustain time. An `AdjudicationOfficer` enforces a `SUSPENSION` action, moving an `ACTIVE` or `RENEWAL_DUE` license to `SUSPENDED`; enforcement cascades to pourers, expiring every attached `ACTIVE` server permit and driving `active_server_count` to zero. A `Director` may later reinstate a `SUSPENDED` license back to `ACTIVE`, provided `outstanding_fine_cents` is zero (otherwise `ERR_OUTSTANDING_FINE`) and `demerit_points` is strictly below ten (otherwise `ERR_DEMERIT_THRESHOLD`). Reinstatement does **not** restore the previously expired server permits — those reached a terminal state and the holders must re-apply.

Enforcing a `REVOCATION` action revokes the license from `ACTIVE`, `SUSPENDED`, or `RENEWAL_DUE`, moving it to `REVOKED`; its attached `ACTIVE` server permits are revoked and `active_server_count` drops to zero. Revocation is terminal — nothing is released or reinstated thereafter.

### 3.11. Three-Tier Compliance Reporting and Excise

Independently of discipline, a licensee files **compliance reports** for the three-tier distribution chain. A report names its `license_id`, a `tier` of `SUPPLIER`, `WHOLESALER`, or `RETAILER`, a non-empty `period_code` matching a four-digit year, a hyphen, the letter `Q`, and a quarter digit one through four (such as `2026-Q1`), and a `gross_sales_cents` of zero or more. On submission the system computes `excise_due_cents` by a tiered assessment with a tier-keyed rebate, evaluated in a pinned order.

First, marginal excise is computed across three sales bands: the first one million cents of `gross_sales_cents` are taxed at two percent; the next four million cents (that is, the portion from one million and one through five million) at four percent; and everything above five million cents at six percent. Each band's tax is rounded half up to whole cents **independently**, and the three rounded band amounts are summed to give the excise. Second, a rebate tier is determined from that **excise** total (not from sales): an excise of fifty thousand cents or less earns no rebate; an excise from fifty thousand and one through two hundred thousand earns a rebate base of five percent of the excise, rounded half up; and an excise above two hundred thousand earns a rebate base of ten percent of the excise, rounded half up. Third, the rebate base is scaled by a tier multiplier — `SUPPLIER` doubles the rebate base, `WHOLESALER` takes it at face value, and `RETAILER` earns no rebate at all — and the scaled rebate is rounded half up. Finally, `excise_due_cents` is the excise minus the rebate, floored at zero.

### 3.12. Transfers and Relocations

A license may change hands or move. A **transfer request** names its `license_id` and a `transfer_type` of `OWNERSHIP` or `LOCATION`. An ownership transfer hands the license to a new applicant and requires `new_applicant_id` (and forbids `new_premise_id`); a location transfer relocates the license to a new premise and requires `new_premise_id` (and forbids `new_applicant_id`). A request that supplies the wrong field for its type — or a location transfer whose target premise sits in a different region than the license — is rejected with `ERR_TRANSFER_TYPE_INVALID` (422). A new request is `PENDING`; the terminal states are `APPROVED` and `REJECTED`. A `Director` rejects a `PENDING` request, moving it to `REJECTED`.

A `Director` approves a `PENDING` request only against a license that is `ACTIVE` with `outstanding_fine_cents` equal to zero (otherwise `ERR_OUTSTANDING_FINE`). For an ownership transfer the prospective new applicant must not be `disqualified` (otherwise `ERR_APPLICANT_DISQUALIFIED`), and on approval the license's applicant association updates to `new_applicant_id`. For a location transfer the target premise must lie in the same region as the license — relocation across regions is forbidden because quota is tied to region — and the target premise must not already host a conflicting license. The conflict test is a **closed-interval** term overlap: among non-terminal licenses (those in `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED`) of the **same** `license_class_code` already located at the target premise, none may have a term window `[term_start_at, term_end_at]` that overlaps the relocating license's term window `[term_start_at, term_end_at]`. Two closed windows conflict when the relocating license's `term_start_at` is less than or equal to the candidate's `term_end_at` and the candidate's `term_start_at` is less than or equal to the relocating license's `term_end_at`. Because the intervals are closed, windows that merely touch at a single endpoint — where one's `term_end_at` equals the other's `term_start_at` — **do** conflict (unlike the half-open hearing-room rule, where touching is allowed). A conflict is rejected with `ERR_PREMISE_TERM_CONFLICT` (409). On a clean location approval the premise is relocated with no region change.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. State-transition and other modifying operations return `200 OK`. The clock-set, quota-status, and re-evaluation reads also return `200 OK`. The table below lists method, path, purpose, and the roles authorised to call each endpoint; request and response bodies are described in the Section 3 narrative.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator |
| POST | `/license-classes` | Create a license class | Director |
| GET | `/license-classes/{id}` | Fetch a license class | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/license-classes` | List license classes | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/quota-regions` | Create a quota region | Director |
| GET | `/quota-regions/{id}` | Fetch a quota region | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/quota-regions` | List/filter quota regions | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/quota-regions/{id}/quota-status` | Computed per-class quota cap/used/available | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| PATCH | `/quota-regions/{id}/moratorium` | Toggle a region moratorium | Director |
| POST | `/applicants` | Register an applicant | Director, LicensingExaminer |
| GET | `/applicants/{id}` | Fetch an applicant | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/applicants/{id}/premises` | List premises owned by an applicant | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/applicants/{id}/applications` | List applications filed by an applicant | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/premises` | Register a premise | Director, LicensingExaminer, Applicant |
| GET | `/premises/{id}` | Fetch a premise | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/license-applications` | Create a DRAFT application | Director, LicensingExaminer, Applicant |
| GET | `/license-applications/{id}` | Fetch an application | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/license-applications` | List/filter applications | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/license-applications/{id}/submit` | Submit a draft application | Applicant |
| POST | `/license-applications/{id}/begin-review` | Begin examiner review | LicensingExaminer |
| POST | `/license-applications/{id}/open-protest-period` | Open the protest window | LicensingExaminer |
| POST | `/license-applications/{id}/approve` | Approve an application | Director |
| POST | `/license-applications/{id}/issue` | Issue the license | Director |
| POST | `/license-applications/{id}/deny` | Deny an application | Director |
| POST | `/license-applications/{id}/withdraw` | Withdraw an application | Applicant |
| POST | `/license-applications/{id}/pay-fee` | Record a fee payment | Applicant |
| GET | `/license-applications/{id}/background-checks` | List the application's background check(s) | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/background-checks/{id}` | Fetch a background check | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/background-checks/{id}/resolve` | Resolve a background check | LicensingExaminer |
| GET | `/license-applications/{id}/zoning-reviews` | List the application's zoning review(s) | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/zoning-reviews/{id}` | Fetch a zoning review | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/zoning-reviews/{id}/decide` | Decide a zoning review | ZoningOfficer |
| POST | `/protests` | File a protest | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant, Anonymous |
| GET | `/protests/{id}` | Fetch a protest | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/license-applications/{id}/protests` | List protests against an application | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/protests/{id}/schedule-hearing` | Schedule a hearing for a protest | AdjudicationOfficer |
| POST | `/protests/{id}/withdraw` | Withdraw a protest | Director |
| GET | `/hearings/{id}` | Fetch a hearing | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/protests/{id}/hearings` | List the hearing(s) for a protest | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/license-applications/{id}/hearings` | List hearings for an application | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/hearings/{id}/render` | Render a hearing outcome | AdjudicationOfficer |
| GET | `/licenses/{id}` | Fetch a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses` | List/filter licenses | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/licenses/{id}/check-renewal-window` | Re-evaluate renewal/expiry posture | Director, LicensingExaminer |
| POST | `/licenses/{id}/renew` | Renew a license | Applicant |
| POST | `/licenses/{id}/reinstate` | Reinstate a suspended license | Director |
| POST | `/licenses/{id}/pay-fine` | Record a fine payment | Applicant |
| POST | `/server-permits` | Create a server permit | Applicant |
| GET | `/server-permits/{id}` | Fetch a server permit | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses/{id}/server-permits` | List permits under a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/server-permits/{id}/activate` | Activate a server permit | Applicant |
| POST | `/server-permits/{id}/revoke` | Revoke a server permit | Director |
| POST | `/server-permits/{id}/check-expiry` | Re-evaluate permit expiry | Director, LicensingExaminer |
| POST | `/violations` | File a violation | Investigator |
| GET | `/violations/{id}` | Fetch a violation | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses/{id}/violations` | List violations against a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/violations/{id}/contest` | Contest a violation | Applicant |
| POST | `/violations/{id}/sustain` | Sustain a violation | AdjudicationOfficer |
| POST | `/violations/{id}/dismiss` | Dismiss a violation | AdjudicationOfficer |
| GET | `/administrative-actions/{id}` | Fetch an administrative action | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/violations/{id}/administrative-actions` | List the action(s) for a violation | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses/{id}/administrative-actions` | List actions against a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/administrative-actions/{id}/enforce` | Enforce a suspension/revocation | AdjudicationOfficer |
| POST | `/compliance-reports` | Submit a three-tier compliance report | Applicant |
| GET | `/compliance-reports/{id}` | Fetch a compliance report | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses/{id}/compliance-reports` | List reports under a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/transfer-requests` | Request an ownership or location transfer | Applicant, Director |
| GET | `/transfer-requests/{id}` | Fetch a transfer request | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/licenses/{id}/transfer-requests` | List transfer requests against a license | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/applicants/{id}/transfer-requests` | List transfers proposing this applicant as new owner | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| GET | `/premises/{id}/transfer-requests` | List transfers proposing this premise as new location | Director, LicensingExaminer, AdjudicationOfficer, ZoningOfficer, Investigator, Applicant |
| POST | `/transfer-requests/{id}/approve` | Approve a transfer request | Director |
| POST | `/transfer-requests/{id}/reject` | Reject a transfer request | Director |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HEARING_ROOM_CONFLICT` | 409 |
| `ERR_STALE_REGION_VERSION` | 412 |
| `ERR_STALE_LICENSE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_APPLICANT_DISQUALIFIED` | 422 |
| `ERR_ZONING_NOT_CLEARED` | 422 |
| `ERR_BACKGROUND_NOT_PASSED` | 422 |
| `ERR_PROTEST_WINDOW_CLOSED` | 422 |
| `ERR_PROTEST_WINDOW_OPEN` | 422 |
| `ERR_PROTEST_UNRESOLVED` | 422 |
| `ERR_SERVER_CAPACITY_EXCEEDED` | 422 |
| `ERR_TRAINING_INCOMPLETE` | 422 |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 422 |
| `ERR_OUTSTANDING_FINE` | 422 |
| `ERR_DEMERIT_THRESHOLD` | 422 |
| `ERR_FEE_UNPAID` | 422 |
| `ERR_QUOTA_EXHAUSTED` | 422 |
| `ERR_TRANSFER_TYPE_INVALID` | 422 |
| `ERR_PREMISE_TERM_CONFLICT` | 409 |
