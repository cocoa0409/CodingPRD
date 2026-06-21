# Credit Report Disputes (FCRA) API — Product Requirements Document

## 1. Introduction

This document specifies a credit-report dispute-management platform modeled on the consumer-protection machinery of the federal Fair Credit Reporting Act (FCRA). When a consumer discovers an inaccurate account on their credit file — a balance that is wrong, a debt that is not theirs, or an obsolete delinquency that has been illegally pushed forward in time — the law grants them the right to dispute it, and it obligates the credit bureau to reinvestigate within a fixed window and the originating data furnisher to reverify the disputed information. The platform models that adversarial-but-regulated workflow end to end: a consumer files a dispute, a bureau opens and runs the investigation, a furnisher answers a reverification request by deleting, correcting, or verifying the account, and the consumer may escalate an unsatisfactory outcome to a regulator such as the Consumer Financial Protection Bureau.

Two forces dominate the design. The first is **time**: every investigation carries a statutory deadline, and the system must auto-resolve any dispute that the bureau and furnisher fail to close in time — under the FCRA, an unverified item left past the deadline must be deleted from the file. The second is **consistency under concurrency**: a consumer can lock or freeze their file at any moment, a freeze can supersede the posture a dispute was filed against, and resolution cascades ripple from a single furnisher response out through the tradeline, the file's derived posture and counts, and an append-only notification log. The platform exposes a flat collection of peer resources — consumers, furnishers, credit files, tradelines, disputes, reverification requests, security freezes, regulatory complaints, notifications, and re-age audit events — that reference one another by identifier, and it enforces the deadlines, the protections, and the cascades atomically inside each triggering request. A test-driving logical clock lets operators set or advance server time deterministically so that deadline behavior can be exercised on demand.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to a non-public endpoint must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED`. The only endpoints that do not require these headers are the two public registration surfaces — registering a consumer and registering a furnisher — which may be called anonymously.

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Consumer`, `Furnisher`, `CreditBureau`, and `Regulator`. When the acting role is present and well-formed but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. Permission is then refined further by ownership: when an authenticated user is permitted by role but does not own the specific target resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The five roles bind to identity in two different ways. `Anonymous` is an opaque, unauthenticated identity used solely for the registration surface; its `X-User-ID` is not tied to any persisted entity and is not compared to any resource. `Consumer` is **entity-backed**: when `X-User-Role` is `Consumer`, the `X-User-ID` is the `id` of the acting `Consumer` entity, and ownership checks on any resource that references a consumer — a dispute, a security freeze, a regulatory complaint, or the credit file underneath them — compare that resource's consumer foreign key (directly, or through its parent credit file's `consumer_id`) to `X-User-ID`. `Furnisher` is likewise entity-backed: when `X-User-Role` is `Furnisher`, the `X-User-ID` is the `id` of the acting `Furnisher`, and ownership checks on a reverification response compare the target reverification request's `furnisher_id` to `X-User-ID`. `CreditBureau` is an opaque operator identity: when `X-User-Role` is `CreditBureau`, the `X-User-ID` is an operational bureau identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `Regulator` is similarly an opaque operator identity representing a CFPB or State Attorney General adjudicator: when `X-User-Role` is `Regulator`, the `X-User-ID` is not tied to any persisted entity and is not compared to any resource's owner.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside 1 through 100, whose `offset` is negative, or whose supplied `limit` or `offset` is not parseable as an integer, is rejected with `ERR_PAGINATION_RANGE`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count` (the count of all matching resources before pagination is applied), and `has_more` (true exactly when `offset` plus the number of items returned in this page is strictly less than `total_count`).

### 2.4. Common Resource Properties and Resource Posture

Every primary resource in the system — a consumer, furnisher, credit file, tradeline, dispute, reverification request, security freeze, and regulatory complaint — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits. These mutable resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every change, and an integer `version` that begins at 1 on creation and increments by one on every mutation of the resource.

Two resource types are append-only event records and therefore carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version`, because they are never modified after they are written. The first is the `Notification`, an immutable entry in the file's event log. The second is the `ReageEvent`, an immutable audit record of a change to a tradeline's reported delinquency date. Both are described in the workflow narratives below.

### 2.5. Hierarchical Consistency and Cascading Resolution

The platform's defining characteristic is that a single operation frequently mutates several resources at once, and all of those mutations complete atomically inside the one triggering request — there is no deferred or eventual reconciliation. When a furnisher's reverification response or a deadline sweep resolves a dispute, the effect cascades from the dispute through its tradeline, then up to the parent credit file's derived counts and posture, and finally into one or more notification records. Whenever a credit file's contents change in a way that the file's derived state depends on, the file's two derived counts are recomputed and, where the scaffold specifies it, the file's `version` is incremented and its `updated_at` refreshed.

The two derived counts on a credit file are maintained continuously. The `open_dispute_count` is the number of disputes on that file whose status is one of `FILED`, `INVESTIGATING`, `REVERIFYING`, or `REOPENED` — that is, disputes that have not yet reached a terminal state. The `tradeline_count` is the number of tradelines on that file whose status is one of `REPORTING`, `DISPUTED`, `CORRECTED`, or `VERIFIED`; tradelines that have reached `DELETED` are excluded from this count. Both counts are recomputed by re-counting the qualifying rows whenever any dispute or tradeline on the file changes state.

### 2.6. Nested Resource Retrieval and Referential Existence

The API is organized as a flat topology of peer collections that reference one another by foreign-key fields carried in request bodies rather than by deep URL nesting. A handful of convenience list endpoints are addressed under a parent identifier — for example, the tradelines, disputes, security freezes, or notifications belonging to a particular credit file, or the re-age events belonging to a particular tradeline or dispute. For any request that carries one or more resource identifiers, whether in the path or as foreign-key fields in the body, the system validates existence left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. This existence check is evaluated before any business-rule or state check, so a request naming a non-existent parent fails on the missing parent rather than on a downstream condition.

### 2.7. Validation Ordering

When a single endpoint is guarded by several checks, those checks are evaluated in a fixed precedence so that the same request always fails on the same, most-fundamental reason. The order is: first, authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then well-formedness of the request body — required input fields present, enum members valid, and numeric types correct, such as a balance supplied as a non-negative integer (`ERR_VALIDATION`), while list endpoints instead range-check pagination through `ERR_PAGINATION_RANGE`; then existence of every path and foreign-key-referenced resource, left to right (`ERR_NOT_FOUND`); then resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`); then the optimistic-concurrency version check (`ERR_STALE_FILE_VERSION`); then the state-machine check that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and only then the domain-specific business rules described throughout Section 3 — the investigation-deadline check, the frozen-file check, the furnisher-suspension check, and the remaining constraint and temporal checks. A failure at any stage short-circuits the rest, so an earlier, more fundamental fault is never masked by a later one.

### 2.8. Optimistic Concurrency on the Credit File

Two write operations are guarded by optimistic concurrency control against the parent credit file, because both depend on the file's protection posture, which another writer may have changed. Both operations require the client to supply `expected_credit_file_version` as a non-optional input field carrying the `version` of the credit file the client last observed.

When a consumer places a security freeze on a credit file, the request must carry `expected_credit_file_version` matching that file's current `version`. If another writer has advanced the file's version since the client last read it — for instance, by placing a freeze that legitimately supersedes the protection posture the current writer planned around — the placement is rejected with `ERR_STALE_FILE_VERSION` (HTTP 412), so the writer cannot act on a stale view of the file. Likewise, when a consumer files a dispute against a credit file, the request must carry `expected_credit_file_version` matching the file's current `version`; if a concurrently placed freeze or a prior dispute's resolution cascade has bumped the file's version (and possibly flipped its posture to `FROZEN`) since the consumer last read it, the dispute creation is rejected with `ERR_STALE_FILE_VERSION` (HTTP 412), ensuring the dispute is filed only against the file state the consumer actually observed. No other endpoint takes a version field.

### 2.9. Date, Time, and Integer Precision

Investigation-deadline arithmetic is performed on UTC instants to microsecond resolution, and the deadline is **inclusive**: an investigation-advancing action whose server clock instant exactly equals the dispute's deadline is in time, while an instant even one microsecond past the deadline breaches it. The seven-year purge calculation is performed in whole days of date arithmetic. The priority score is an integer computed with integer floor division and clamped to the range 0 through 100. Monetary balances are held and reported as integer cents; there is no fractional-currency rounding anywhere in this domain.

## 3. Business Logic & Workflows

### 3.1. Registering the Participants and Opening a File

The cast of the dispute process registers itself before any credit data exists. A **consumer** is registered anonymously by supplying an `email` that serves as the login identity, a `full_name` giving the consumer's full legal name, and `ssn_last4`, the last four digits of the Social Security number, which must be exactly four numeric characters. Every consumer is created in, and permanently remains in, the `ACTIVE` status; the `status` field is set by the system at registration and is never anything else in this model.

An **information furnisher** — a bank, a card issuer, a collection agency, or a lender — registers anonymously with a `name` and a `furnisher_type` drawn from `BANK`, `CARD_ISSUER`, `COLLECTION_AGENCY`, or `LENDER`. A furnisher begins in `status` `ACTIVE` and carries an `open_reverification_count` that starts at 0 and tracks how many reverification requests addressed to that furnisher are currently pending. A bureau may later suspend a furnisher as a compliance action, moving its `status` to `SUSPENDED`; a `SUSPENDED` furnisher cannot be issued new reverification work, as described in Section 3.4.

A **credit file** is opened by a bureau for a particular consumer at a particular bureau, supplying the `consumer_id` of the file's owner and a `bureau_code` of `EQUIFAX`, `EXPERIAN`, or `TRANSUNION`. A freshly opened file starts with a `protection_state` of `OPEN`, an `open_dispute_count` of 0, a `tradeline_count` of 0, and a `version` of 1. The file's `protection_state`, one of `OPEN`, `LOCKED`, or `FROZEN`, is never set directly; it is always derived from the file's security freezes against the current clock, as detailed in Section 3.7. When a credit file is fetched, its posture is recomputed against the current server clock before it is returned, so a freeze that has expired by the passage of time is reflected even if no other write has touched the file.

### 3.2. Reporting Tradelines and the Re-Aging Audit Trail

A **tradeline** is an individual account line on a credit file, reported either by a furnisher or by a bureau on a furnisher's behalf. Creating one requires the `credit_file_id` it attaches to, the `furnisher_id` that owns it, an `account_type` of `REVOLVING`, `INSTALLMENT`, or `COLLECTION`, a `balance_cents` reported balance that must be an integer of at least 0, a `date_of_first_delinquency` (the DOFD), and a `reported_delinquency_date` reflecting the delinquency date currently being reported. On creation the reported delinquency date must be on or after the date of first delinquency; a reported delinquency date earlier than the DOFD is rejected with `ERR_INVALID_DELINQUENCY_DATE`. A new tradeline enters `status` `REPORTING`, and the parent file's `tradeline_count` is recomputed to include it.

Two derived fields are computed for every tradeline at creation and recomputed on any later change to its reported delinquency date. The first is `reage_violation`, a boolean that is true exactly when the reported delinquency date lies strictly after the date of first delinquency, and false when the two dates are equal or when the reported date is earlier — equality is legal and is not a violation. Re-aging is the illegal practice of moving the reported delinquency date forward past the true date of first delinquency, which would improperly reset the seven-year reporting clock. The second derived field is `purge_due_at`, the instant on or after which the obsolete adverse item must be purged: it is the date of first delinquency plus seven years (modeled as seven times 365, i.e. 2555 days, with leap days ignored) plus a further 180 days. The purge instant is anchored to the date of first delinquency alone and never to the reported delinquency date, so re-aging an account can never push its purge date outward.

A furnisher may directly re-age a tradeline it owns by submitting a new `reported_delinquency_date`. Doing so recomputes the tradeline's `reage_violation` flag against the unchanged date of first delinquency, leaves `purge_due_at` untouched (since the purge anchor never moves), and appends an immutable **re-age event** to the tradeline's audit trail. Each re-age event records the `tradeline_id` it concerns, the `prior_delinquency_date` (the reported delinquency date before the change), the `new_delinquency_date` (the reported delinquency date after the change), a `was_violation` boolean that is true when the new reported delinquency date is strictly later than the date of first delinquency at the moment of the event, and a `source_dispute_id` identifying the dispute whose reverification triggered the re-age, or null for a direct furnisher edit such as this one.

### 3.3. Filing a Dispute

A consumer initiates a dispute against a specific tradeline on their own file. The filing payload carries the `credit_file_id`, the `tradeline_id` under dispute, a `dispute_reason`, an optional `clock_mode`, and the `expected_credit_file_version` for the concurrency check described in Section 2.8. The `dispute_reason` is one of `NOT_MINE`, `INACCURATE_BALANCE`, `ILLEGAL_REAGE`, `PAID_IN_FULL`, or `IDENTITY_THEFT`. The `clock_mode` selects which deadline variant applies and is one of `CALENDAR` or `EXPEDITED`, defaulting to `CALENDAR` when omitted. The dispute's `consumer_id` is not supplied by the client; the system copies it from the referenced credit file's owner at creation. A newly filed dispute enters `status` `FILED`, its `filed_at` is stamped with the current server clock, its `reopen_count` begins at 0, and its `outcome_reason` begins null.

Several conditions must hold for a filing to succeed, and they are evaluated in the precedence of Section 2.7. The consumer must own the target file, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. The supplied `expected_credit_file_version` must match the file's current `version`, or the filing is rejected with `ERR_STALE_FILE_VERSION`. The parent credit file must not be `FROZEN`; filing against a frozen file is rejected with `ERR_FILE_FROZEN`. The target tradeline must be in a disputable status — `REPORTING`, `CORRECTED`, or `VERIFIED` — or the request is rejected with `ERR_TRADELINE_NOT_DISPUTABLE` (for instance, a tradeline already `DISPUTED` or already `DELETED` cannot be disputed afresh). No other non-terminal dispute may already reference the target tradeline, or the request is rejected with `ERR_DUPLICATE_DISPUTE`. Finally, a window-overlap rule applies, described just below.

The **overlapping-investigation** rule guards against duplicate reinvestigations of the same grievance. A new dispute's investigation window runs from its `filed_at` up to but not including its `deadline_at`. The new dispute is rejected with `ERR_OVERLAPPING_INVESTIGATION` if, on the same credit file, there exists any other non-terminal dispute (status `FILED`, `INVESTIGATING`, `REVERIFYING`, or `REOPENED`) that carries the **same** `dispute_reason` and whose window overlaps the new one. The windows are half-open with zero buffer: they overlap exactly when the new dispute's `filed_at` is earlier than the existing dispute's `deadline_at` and the existing dispute's `filed_at` is earlier than the new dispute's `deadline_at`. This aggregate check is scoped per credit file and per dispute reason, and is distinct from the pairwise single-file freeze-overlap rule of Section 3.7.

When all conditions hold, the dispute is created in `FILED`, the disputed tradeline transitions from `REPORTING`, `CORRECTED`, or `VERIFIED` to `DISPUTED`, the file's `open_dispute_count` is recomputed to include the new dispute, a notification with `event_code` `DISPUTE_FILED` is minted on the file, and the file's `version` is incremented by one.

### 3.4. The Investigation Clock and Triage Priority

Every dispute's `deadline_at` is computed at filing time from its `filed_at` and its `clock_mode`, and once computed it is frozen — it is never recomputed, even across reopen cycles. Under `CALENDAR` mode, the deadline is the filing instant plus 30 calendar days, with weekends counted normally; this is the standard FCRA reinvestigation window. Under `EXPEDITED` mode — used for a reinvestigation triggered by a regulator-referred complaint — the deadline is the filing instant advanced by 15 business days: starting from the filing date, the system steps forward one calendar day at a time, counting only days that fall on Monday through Friday and skipping every Saturday and Sunday, until 15 such weekdays have been added, while preserving the time-of-day component of the filing instant. The two variants take the same inputs and produce different instants. As stated in Section 2.9, the deadline is inclusive: an advancing action exactly at the deadline instant is in time, and one microsecond past it breaches.

Each dispute also carries a `priority_score`, an integer triage score in the range 0 through 100, computed at filing and recomputed whenever the dispute is reopened. The score begins from a reason weight determined by the `dispute_reason`: 50 for `IDENTITY_THEFT`, 40 for `ILLEGAL_REAGE`, 35 for `NOT_MINE`, 20 for `INACCURATE_BALANCE`, and 15 for `PAID_IN_FULL`. To this is added a re-age bonus of 25 points when the linked tradeline's `reage_violation` flag is true, and 0 when it is false. A balance factor is then added, equal to the tradeline's `balance_cents` divided by 50000 using integer floor division — one point per 500 dollars of reported balance — but capped so that the balance factor never exceeds 20. A reopen penalty is then subtracted, equal to 10 points for each prior reopen cycle, that is, 10 multiplied by the dispute's `reopen_count`. The resulting raw total is then clamped into the range 0 through 100: any value below 0 becomes 0 and any value above 100 becomes 100.

A bureau opens the reinvestigation, advancing the dispute from `FILED` to `INVESTIGATING`. Opening requires that the dispute currently be `FILED` (otherwise `ERR_INVALID_STATE`), then — in the business-rule precedence of Section 2.7 — that the server clock be at or before the dispute's deadline (otherwise the deadline has been breached and `ERR_DEADLINE_BREACHED` applies), and then that the parent file not be `FROZEN` (otherwise `ERR_FILE_FROZEN`); the deadline check is evaluated before the frozen-file check. Opening the investigation changes no tradeline and leaves the file's open-dispute count unchanged, since the dispute remains non-terminal.

### 3.5. Reverification: Dispatch, Response, and Cascade

With a dispute under investigation, the bureau dispatches a **reverification request** to the furnisher that owns the disputed tradeline, supplying the `dispute_id` and the `furnisher_id`. Dispatching requires that the dispute be in `INVESTIGATING` (or in `REOPENED`, the reopened-cycle case described in Section 3.6, otherwise `ERR_INVALID_STATE`), then — in the business-rule precedence of Section 2.7 — that the server clock be at or before the dispute's deadline (otherwise `ERR_DEADLINE_BREACHED`), and then that the target furnisher's `status` be `ACTIVE` (otherwise `ERR_FURNISHER_SUSPENDED`); the deadline check is evaluated before the furnisher-suspension check. Dispatch creates a reverification request in `status` `PENDING`, advances the dispute to `REVERIFYING`, and increments the target furnisher's `open_reverification_count` by one. A pending reverification request carries a `response_type` that is null until the furnisher answers, and a `corrected_balance_cents` that is supplied only with a correcting response and is otherwise null.

The owning furnisher then responds with a `response_type` of `DELETE`, `MODIFY`, or `VERIFY`; a correcting response may also carry a `corrected_balance_cents` and a `corrected_delinquency_date`. Any response requires, in the precedence of Section 2.7, that the acting furnisher be the request's own `furnisher_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), then that the reverification request still be `PENDING` (otherwise `ERR_INVALID_STATE`), and then that the server clock be at or before the dispute's deadline (otherwise `ERR_DEADLINE_BREACHED`); the ownership check is evaluated before the `PENDING`-state check. Whichever branch is taken, the reverification request moves from `PENDING` to `RESPONDED` with its `response_type` recorded, the furnisher's `open_reverification_count` is decremented by one, and the dispute reaches one of three terminal resolutions. The three branches are siblings of equal standing and each drives a distinct cascade.

When the furnisher answers `DELETE`, the dispute resolves to `RESOLVED_DELETE` with `outcome_reason` `FURNISHER_DELETED`. The cascade then deletes the tradeline: the disputed tradeline moves to `DELETED`, after which the file's `tradeline_count` is recomputed downward by one and its `open_dispute_count` is recomputed downward by one, and finally two notifications are minted on the file — one with `event_code` `TRADELINE_DELETED` and one with `event_code` `DISPUTE_RESOLVED`. The file's `version` is incremented by one.

When the furnisher answers `MODIFY`, the response must include a `corrected_balance_cents` supplied as an integer of at least 0; a modifying response that omits it, or that supplies it as a non-integer (booleans are not accepted as integers) or as a negative integer, is rejected with `ERR_MISSING_CORRECTED_BALANCE`. This balance check is evaluated only after the ownership, `PENDING`-state, and deadline checks above have passed. The dispute resolves to `RESOLVED_CORRECT` with `outcome_reason` `FURNISHER_CORRECTED`. The cascade replaces the tradeline's `balance_cents` with the supplied `corrected_balance_cents` and moves the tradeline from `DISPUTED` to `CORRECTED`; if a `corrected_delinquency_date` is supplied and it is strictly later than the date of first delinquency, a re-age event is appended (with its `source_dispute_id` set to this dispute) and the tradeline's `reage_violation` flag is recomputed. The file's `tradeline_count` is recomputed and its `open_dispute_count` is recomputed downward by one, a notification with `event_code` `TRADELINE_CORRECTED` is minted, and the file's `version` is incremented by one.

When the furnisher answers `VERIFY`, the dispute resolves to `RESOLVED_VERIFY` with `outcome_reason` `FURNISHER_VERIFIED`. The tradeline moves from `DISPUTED` to `VERIFIED` with its balance unchanged, the file's `open_dispute_count` is recomputed downward by one, a notification with `event_code` `DISPUTE_RESOLVED` is minted, and the file's `version` is incremented by one.

### 3.6. Reopening, Deadline Breach, and Auto-Deletion

A consumer who is dissatisfied with a reverification outcome may reopen the dispute while it is in `REVERIFYING`, supplying new evidence to force a second look. Reopening requires that the dispute be in `REVERIFYING`, that the acting consumer own the dispute (otherwise `ERR_NOT_RESOURCE_OWNER`), that the dispute's `reopen_count` be less than 2 (otherwise `ERR_REOPEN_LIMIT_REACHED`, since a dispute may be reopened at most twice), and that the server clock be at or before the dispute's deadline (otherwise `ERR_DEADLINE_BREACHED`). Reopening advances the dispute from `REVERIFYING` to `REOPENED`, increments its `reopen_count` by one, and recomputes its `priority_score` (the reopen penalty now reducing it). Any reverification request still `PENDING` for this dispute is cancelled — moved to `CANCELLED` — and the furnisher's `open_reverification_count` is decremented by one for each request so cancelled. The tradeline remains `DISPUTED` throughout. From `REOPENED`, the bureau may dispatch a fresh reverification request, which again advances the dispute to `REVERIFYING` and increments the furnisher's open count, forming the revision loop. Because the deadline is frozen at filing, every reopen cycle still races against the original deadline.

The deadline itself is enforced by a clock-driven sweep. Whenever the logical clock is advanced (as opposed to merely set), the system sweeps every dispute whose status is non-terminal — `FILED`, `INVESTIGATING`, `REVERIFYING`, or `REOPENED` — and whose deadline now lies strictly before the new clock instant, and auto-deletes it. An auto-deleted dispute moves to `AUTO_DELETED` with `outcome_reason` `DEADLINE_BREACH`, reflecting the FCRA mandate that an item unresolved past the reinvestigation window must be deleted. The cascade mirrors the furnisher-delete cascade: the tradeline moves to `DELETED`, the file's `tradeline_count` and `open_dispute_count` are recomputed, and notifications with `event_code` `DISPUTE_AUTO_DELETED` and `event_code` `TRADELINE_DELETED` are minted on the file. Additionally, any reverification request still `PENDING` for the breached dispute is moved to `EXPIRED`, with the furnisher's `open_reverification_count` decremented by one per expired request. The file's `version` is incremented by one. Both clock operations take the target instant as a `to_iso8601` field. Distinguishing the two clock operations matters: setting the clock moves server time to the supplied `to_iso8601` without running the sweep, whereas advancing the clock moves server time to the supplied `to_iso8601` and runs the sweep.

### 3.7. Locks, Freezes, and the Derived Protection Posture

A consumer protects their file by placing a **security freeze**, supplying the `credit_file_id`, a `freeze_type`, an `effective_at` instant, an optional `expires_at` instant, and the `expected_credit_file_version` for the concurrency check of Section 2.8. The `freeze_type` is either `LOCK` — a consumer-toggled convenience posture — or `FREEZE`, the stronger statutory protection that blocks new tradeline pulls and dispute creation. The `effective_at` marks the inclusive start of a half-open active interval and the `expires_at` marks its exclusive end; an `expires_at` of null means the protection is open-ended with no expiry. A new freeze is created in `status` `ACTIVE`. Placement must own the file (otherwise `ERR_NOT_RESOURCE_OWNER`) and must pass the version check (otherwise `ERR_STALE_FILE_VERSION`). A new freeze interval must not overlap an existing `ACTIVE` freeze of the **same** `freeze_type` on the same file; because the intervals are half-open, two freezes that merely abut — one ending exactly where the next begins — do not overlap, but any genuine overlap is rejected with `ERR_FREEZE_OVERLAP`. Placing a freeze recomputes the file's protection posture, mints a notification with `event_code` `FREEZE_PLACED`, and increments the file's `version` by one.

The file's `protection_state` is a pure derivation, recomputed on any freeze placement or lift and whenever the file is read, evaluated against the current server clock. The system considers the set of that file's freezes that are simultaneously `ACTIVE` in status and whose half-open interval currently contains the clock — that is, whose `effective_at` is at or before the clock and whose `expires_at` is either null or strictly after the clock. If any freeze in that active set has `freeze_type` `FREEZE`, the posture is `FROZEN`; otherwise, if any has `freeze_type` `LOCK`, the posture is `LOCKED`; otherwise the posture is `OPEN`. A `FREEZE` strictly dominates a `LOCK`. A `FROZEN` posture blocks both new dispute creation and opening an investigation, as enforced by the `ERR_FILE_FROZEN` checks elsewhere.

A consumer lifts a freeze they own, moving it from `ACTIVE` to `LIFTED`. Lifting requires that the freeze be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and that the acting consumer own the parent file (otherwise `ERR_NOT_RESOURCE_OWNER`). Lifting recomputes the file's `protection_state`, increments the file's `version` by one, and mints a notification with `event_code` `FREEZE_LIFTED`.

### 3.8. Escalating to a Regulator

When a consumer believes a dispute was mishandled, they file a **regulatory complaint** about it, supplying the `dispute_id`, an optional `agency`, and a free-text `narrative`. The `agency` is either `CFPB` or `STATE_AG`, defaulting to `CFPB` when omitted. The complaint's `consumer_id` is copied by the system from the referenced dispute's consumer. A new complaint enters `status` `SUBMITTED`, and a notification with `event_code` `COMPLAINT_SUBMITTED` is minted on the dispute's credit file; minting this notification does not itself alter the credit file (its `version` and `updated_at` are left unchanged), since filing a complaint does not mutate the file.

A regulator works the complaint in two steps. First, the regulator moves it from `SUBMITTED` to `UNDER_REVIEW`; this transition requires the complaint to currently be `SUBMITTED`, otherwise `ERR_INVALID_STATE`. Then the regulator adjudicates it by supplying a `decision` of either `UPHOLD` or `DISMISS`. Adjudication requires the complaint to be `UNDER_REVIEW`, otherwise `ERR_INVALID_STATE`; this `UNDER_REVIEW`-state check is evaluated before the decision value itself is validated, and only then is any decision value other than `UPHOLD` or `DISMISS` rejected with `ERR_INVALID_DECISION` (the `decision` field must still be present, or the request fails the well-formedness check with `ERR_VALIDATION`). A `DISMISS` decision moves the complaint to `DISMISSED`. An `UPHOLD` decision moves it to `UPHELD`, but only if the referenced dispute has itself reached a contestable terminal state — its status must be `AUTO_DELETED` or `RESOLVED_VERIFY` — since a complaint can be upheld only once the underlying dispute has actually concluded against the consumer; upholding while the dispute is in any other state is rejected with `ERR_COMPLAINT_PREMATURE`. Either adjudication outcome mints a notification with `event_code` `COMPLAINT_ADJUDICATED` on the dispute's credit file; as with submission, minting this notification leaves the credit file's `version` and `updated_at` unchanged.

### 3.9. The Notification Event Log

Every materially significant event in a file's history is recorded as an immutable **notification** on that file. A notification carries the `credit_file_id` it belongs to, a `subject_type` naming the kind of entity the event concerns — one of `DISPUTE`, `SECURITY_FREEZE`, `REGULATORY_COMPLAINT`, or `TRADELINE` — and a `subject_id` that is the identifier of that subject entity, resolved polymorphically according to the `subject_type`. Each notification also carries an `event_code` drawn from `DISPUTE_FILED`, `DISPUTE_RESOLVED`, `DISPUTE_AUTO_DELETED`, `TRADELINE_CORRECTED`, `TRADELINE_DELETED`, `FREEZE_PLACED`, `FREEZE_LIFTED`, `COMPLAINT_SUBMITTED`, or `COMPLAINT_ADJUDICATED`, and a `dispatched_at` timestamp recording the server clock instant at which it was minted. Notifications are never modified after they are written; they form an append-only log that, together with the re-age events of Section 3.2, gives every credit file a complete and tamper-evident audit trail.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code; operations that modify an existing resource, drive a state transition, or merely read return a `200 OK` status code. Requests must carry the `X-User-ID` and `X-User-Role` headers on every endpoint except the two anonymous registration endpoints. To reconstruct the full request body, side effects, and cascades of any endpoint, refer to the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/consumers` | Register a consumer | Anonymous |
| GET | `/consumers/{consumerId}` | Get a consumer | Consumer, CreditBureau, Regulator |
| POST | `/furnishers` | Register an information furnisher | Anonymous |
| GET | `/furnishers/{furnisherId}` | Get a furnisher | Furnisher, CreditBureau, Regulator |
| POST | `/furnishers/{furnisherId}/suspend` | Suspend a furnisher | CreditBureau |
| POST | `/credit-files` | Open a credit file for a consumer at a bureau | CreditBureau |
| GET | `/credit-files/{creditFileId}` | Get a credit file with derived posture and counts | Consumer, CreditBureau, Regulator |
| GET | `/credit-files` | List credit files, filterable by consumer | CreditBureau, Regulator |
| GET | `/credit-files/{creditFileId}/tradelines` | List tradelines on a credit file | Consumer, CreditBureau, Regulator |
| GET | `/credit-files/{creditFileId}/disputes` | List disputes on a credit file | Consumer, CreditBureau, Regulator |
| GET | `/credit-files/{creditFileId}/security-freezes` | List security freezes on a credit file | Consumer, CreditBureau, Regulator |
| GET | `/credit-files/{creditFileId}/notifications` | List notifications for a credit file | Consumer, CreditBureau, Regulator |
| POST | `/tradelines` | Report a tradeline onto a credit file | Furnisher, CreditBureau |
| GET | `/tradelines/{tradelineId}` | Get a tradeline | Consumer, Furnisher, CreditBureau, Regulator |
| GET | `/tradelines` | List tradelines, filterable by furnisher or credit file | Furnisher, CreditBureau, Regulator |
| GET | `/tradelines/{tradelineId}/reage-events` | List re-age events for a tradeline | Consumer, Furnisher, CreditBureau, Regulator |
| POST | `/tradelines/{tradelineId}/reage` | Furnisher directly re-ages a tradeline | Furnisher |
| POST | `/disputes` | File a dispute against a tradeline | Consumer |
| GET | `/disputes/{disputeId}` | Get a dispute | Consumer, CreditBureau, Furnisher, Regulator |
| GET | `/disputes` | List disputes, filterable by tradeline, consumer, or credit file | Consumer, CreditBureau, Regulator |
| POST | `/disputes/{disputeId}/open-investigation` | Open the reinvestigation | CreditBureau |
| GET | `/disputes/{disputeId}/reage-events` | List re-age events triggered by this dispute | Consumer, CreditBureau, Furnisher, Regulator |
| POST | `/disputes/{disputeId}/reopen` | Reopen a dispute with new evidence | Consumer |
| POST | `/reverification-requests` | Dispatch reverification to the furnisher | CreditBureau |
| GET | `/reverification-requests/{reverificationId}` | Get a reverification request | Consumer, CreditBureau, Furnisher, Regulator |
| GET | `/reverification-requests` | List reverification requests, filterable by dispute or furnisher | CreditBureau, Furnisher, Regulator |
| POST | `/reverification-requests/{reverificationId}/respond` | Furnisher responds DELETE, MODIFY, or VERIFY | Furnisher |
| POST | `/security-freezes` | Place a lock or freeze on a credit file | Consumer |
| GET | `/security-freezes/{freezeId}` | Get a security freeze | Consumer, CreditBureau, Regulator |
| GET | `/security-freezes` | List security freezes, filterable by credit file | Consumer, CreditBureau, Regulator |
| POST | `/security-freezes/{freezeId}/lift` | Lift a freeze or lock | Consumer |
| POST | `/regulatory-complaints` | File a CFPB or State AG complaint about a dispute | Consumer |
| GET | `/regulatory-complaints/{complaintId}` | Get a regulatory complaint | Consumer, Regulator, CreditBureau |
| GET | `/regulatory-complaints` | List regulatory complaints, filterable by dispute or consumer | Regulator, CreditBureau, Consumer |
| POST | `/regulatory-complaints/{complaintId}/review` | Move a complaint to UNDER_REVIEW | Regulator |
| POST | `/regulatory-complaints/{complaintId}/adjudicate` | Uphold or dismiss a complaint | Regulator |
| GET | `/notifications/{notificationId}` | Get a single notification | Consumer, CreditBureau, Regulator |
| GET | `/notifications` | List notifications, filterable by credit file or subject | Consumer, CreditBureau, Regulator |
| GET | `/reage-events/{reageEventId}` | Get a single re-age event | Consumer, Furnisher, CreditBureau, Regulator |
| GET | `/reage-events` | List re-age events, filterable by tradeline or source dispute | Consumer, Furnisher, CreditBureau, Regulator |
| POST | `/_clock/set` | Set the server clock without running the deadline sweep | CreditBureau |
| POST | `/_clock/advance` | Advance the server clock and run the deadline sweep | CreditBureau |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_DELINQUENCY_DATE` | 422 |
| `ERR_STALE_FILE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEADLINE_BREACHED` | 409 |
| `ERR_FILE_FROZEN` | 409 |
| `ERR_FURNISHER_SUSPENDED` | 409 |
| `ERR_TRADELINE_NOT_DISPUTABLE` | 409 |
| `ERR_DUPLICATE_DISPUTE` | 409 |
| `ERR_OVERLAPPING_INVESTIGATION` | 409 |
| `ERR_REOPEN_LIMIT_REACHED` | 409 |
| `ERR_MISSING_CORRECTED_BALANCE` | 422 |
| `ERR_FREEZE_OVERLAP` | 409 |
| `ERR_COMPLAINT_PREMATURE` | 409 |
| `ERR_INVALID_DECISION` | 422 |
| `ERR_PAGINATION_RANGE` | 422 |
