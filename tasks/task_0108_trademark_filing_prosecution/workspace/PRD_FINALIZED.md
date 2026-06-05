# Trademark Filing & Prosecution API — Product Requirements Document

## 1. Introduction

Trademark prosecution is a long-running, deadline-saturated discipline. A single mark may live for decades, passing through an examining attorney's office, a publication window open to public opposition, a Trial and Appeal Board docket, and a perpetual cycle of post-registration maintenance — all while a parallel international registration rides on the fate of the underlying domestic mark. The cost of a missed window is rarely a fee; it is the irretrievable loss of the mark itself. This API exists to model that lifecycle faithfully: to let applicants and their counsel file marks, respond to examiner refusals, allege use, prosecute and defend board proceedings, renew registrations, and extend protection abroad, with every statutory clock computed and docketed by the server rather than trusted to a human calendar.

The system serves four distinct constituencies whose interests deliberately diverge. **Applicants** own marks and may self-represent in limited circumstances; **Attorneys** prosecute on behalf of those applicants and bear the professional duty of timeliness; **Examiners** act for the trademark office, issuing refusals, approving publication, granting registration, and accepting maintenance; and **TTABClerks** administer the adversarial board proceedings through which third parties attack pending and registered marks. Because the same calendar date can mean "timely" to one party and "defaulted" to another, the API treats time as a first-class, server-controlled input and resolves every deadline through explicit, testable windows rather than wall-clock guesswork.

A guiding design principle runs throughout: state is advanced only through named transitions, every transition that opens or closes a statutory window writes a corresponding docket entry, and the financial and concurrency consequences of each action are computed deterministically so that two clients observing the same resource never diverge on what happens next.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Applicant`, `Attorney`, `Examiner`, and `TTABClerk`.

The two private parties are **entity-backed**. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` compare the resource's applicant foreign key (for example, an application's `applicant_id`, or a proceeding's `petitioner_applicant_id`) to `X-User-ID`. When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney`; ownership checks on any resource that references an `Attorney` compare the resource's `attorney_id` (the attorney of record) to `X-User-ID`. When an entity-backed acting role attempts to mutate a resource it does not own — an applicant acting on another applicant's mark, or an attorney acting where it is not the attorney of record — the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The two office parties are **opaque operators**. When `X-User-Role` is `Examiner`, `X-User-ID` is an opaque operator identifier representing the examining attorney; it is not tied to any persisted entity and is never compared to any entity's `id`. When `X-User-Role` is `TTABClerk`, `X-User-ID` is likewise an opaque board-administrator identifier not tied to any persisted entity. The server may record these identifiers operationally, but never treats them as ownership keys.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Versioning Model

Most resources in this system are mutable records that carry a standard system-managed property set:

- `id` — a unique, server-minted UUID with no type prefix. It identifies the resource and is never accepted as a business-decision input.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control described in §2.6.

These four properties are carried by `Applicant`, `Attorney`, `TrademarkApplication`, `GoodsServicesItem`, `OfficeAction`, `OfficeActionResponse`, `StatementOfUse`, `TTABProceeding`, `Registration`, `MaintenanceFiling`, `MadridApplication`, and `DocketDeadline`.

One entity is an exception: a `NiceClass` is an immutable reference record. It carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because once seeded a class code never changes.

Whenever the server advances a resource's state or recomputes one of its derived fields, that counts as a mutation: the resource's `updated_at` is refreshed and its `version` is incremented by one. This applies equally to the automatic, server-initiated transitions described later (sweeps and cascades), not only to client-requested ones.

### 2.5. Polymorphic Docketing and Nested Resource Retrieval

The system maintains a single deadline ledger. Each `DocketDeadline` is a polymorphic row whose `subject_type` names the kind of parent it belongs to — one of `OFFICE_ACTION`, `OPPOSITION_ANSWER`, `SOU`, `MAINTENANCE`, or `OPPOSITION_WINDOW` — and whose `subject_id` holds the `id` of that parent (an office action, a proceeding, an application, or a registration, according to the `subject_type`). For docket-listing convenience, each deadline also records an `application_id` to which it rolls up; this is null for `MAINTENANCE` deadlines, which roll up to a registration rather than to a pending application. Each deadline carries a `due_at` timestamp (computed by the transition that creates it and passed in at creation) and a `status` that begins at `PENDING` and moves to `MET`, `MISSED`, or `CANCELLED` as its parent's workflow resolves.

For any endpoint whose path contains more than one resource identifier, the server validates identifiers strictly left-to-right. The first identifier in the path that does not resolve to an existing row causes the request to fail immediately with `ERR_NOT_FOUND`, before any later identifier or body foreign key is examined. Body foreign keys are validated only after every path identifier has resolved, again in declared order, and a non-resolving body reference likewise yields `ERR_NOT_FOUND`.

### 2.6. Optimistic Concurrency on Supersede-Style Creates

Two creation endpoints permit a client to supersede an earlier, still-pending submission against the same parent, and both are guarded by optimistic concurrency control to stop a client from overwriting state it has not yet observed.

Filing a Statement of Use requires the request to carry `expected_application_version`, a non-optional field holding the client's last observed `version` of the target `TrademarkApplication`. If that value does not equal the application's current `version` — because some other writer advanced the application since the client last read it — the create is rejected with `ERR_STALE_VERSION` at HTTP 412. The product deliberately allows a corrected Statement of Use to supersede a prior one while the application remains `ALLOWED`, which is exactly why a writer holding a stale view must be turned away on the version check rather than silently replacing the newer state.

Filing a maintenance filing requires the request to carry `expected_registration_version`, a non-optional field holding the client's last observed `version` of the target `Registration`. If that value does not equal the registration's current `version`, the create is rejected with `ERR_STALE_VERSION` at HTTP 412. As with statements of use, a corrected §8/§9 filing may legitimately supersede a prior submitted one for the same cycle, so a stale-version writer is rejected on the version check.

No other endpoint accepts a version field; endpoints not named here perform no concurrency check.

### 2.7. Statutory Windows and the Server Clock

Every deadline in this system is derived from a transition timestamp plus a fixed statutory offset, so that windows are well-defined and reproducible. Day-based offsets are counted in whole calendar days; year-based offsets are counted in calendar years that preserve the original month and day. Because so much of the workflow is time-gated, the server exposes an administrative test-driving capability through which an operator sets the server's current UTC instant by supplying a `to_iso8601` value; all subsequent reads of "now" return that instant until it is set again. This lets time-dependent transitions — expiries, defaults, grace entries — be exercised deterministically.

The concrete windows are as follows, all measured from the timestamp of the triggering transition. An office action's response period is 90 days. A non-final office action tolerates a late response within a further 30-day grace tail after the response period closes; a final office action grants no such tail (its grace tail is zero days), so any late response to a final action is refused. The opposition window stays open for 30 days after publication. A defendant's answer period in a board proceeding is 40 days. After a Notice of Allowance, the initial Statement-of-Use window is 180 days, and the absolute outer limit including every granted extension is 1260 days from the Notice of Allowance. A Madrid international registration remains dependent on its basic mark for 5 years from the basic application's filing.

### 2.8. Fee Computation and Monetary Precision

All monetary amounts in this system are expressed as whole United States cents and stored as integers; every fee input is a whole-cent constant, so fee arithmetic is exact and never requires rounding. The system computes three kinds of fees — application filing fees, post-registration maintenance fees, and Madrid international fees — and each is pinned to a precise tiered or aggregated formula detailed in §3. A fee, once computed and locked by its triggering transition, does not drift if unrelated facts change later.

### 2.9. Portfolio Risk Scoring

Beyond the per-mark workflow, the system computes a portfolio-level **prosecution risk score** for an applicant: a bounded integer estimate, from 0 to 100, of the likelihood that the applicant's portfolio suffers a lapse. This score is a read-time computation over every office action, response, proceeding, and registration reachable from the applicant's applications; its exact weighting and its optional projected variant are specified in §3.7. The score is reported alongside the `applicant_id` it was computed for and the name of the `variant` used.

## 3. Business Logic & Workflows

### 3.1. Parties, Reference Data, and Draft Applications

The system's private parties are registered first. Registering an `Applicant` captures a `legal_name`, an `entity_type` — one of `INDIVIDUAL`, `CORPORATION`, `PARTNERSHIP`, or `LLC` — and a two-uppercase-letter ISO-3166 `country_code`. From the country, the server derives `is_foreign_domiciled`, which is true exactly when the `country_code` is not `US`; a foreign-domiciled applicant cannot prosecute alone, as enforced at filing time below. A new applicant's `open_application_count`, the running count of its applications not yet in a terminal `REGISTERED` or `ABANDONED` state, begins at 0.

Registering an `Attorney` captures a `full_name`, a `bar_number`, and a two-uppercase-letter `bar_state`. The `bar_number` must be unique across all attorneys; a second registration of the same number is refused with `ERR_DUPLICATE_BAR_NUMBER`. An attorney's bar `status` starts at `ACTIVE` and may later be moved to `SUSPENDED` by an examiner exercising bar discipline; suspension is a mutation that increments the attorney's `version`. Only an `ACTIVE` attorney may serve as attorney of record at filing.

Nice classification codes are seeded by an examiner. A `NiceClass` carries a `class_number` (an integer from 1 to 45, unique across all classes — a duplicate is refused with `ERR_DUPLICATE_NICE_CLASS`) and a short `title`. The server derives `is_service_class`, true exactly when the `class_number` is between 35 and 45 inclusive and false for the goods classes numbered 1 through 34.

A `TrademarkApplication` is created in `DRAFT` status by an applicant or an attorney, supplying the owning `applicant_id`, an optional `attorney_id` (the prosecuting attorney of record, which may be omitted only when a US-domiciled applicant self-represents), the `mark_text` (the literal standard-character element, non-empty and at most 200 characters), the `filing_basis`, and the `filing_tier`. The `filing_basis` is either `USE` (the mark is already in commerce under §1(a)) or `INTENT` (a §1(b) intent-to-use reservation). The `filing_tier` is either `TEAS_PLUS` or `TEAS_STANDARD`. On creation, the application's `status` is `DRAFT`, and its computed fields — `class_count`, `filing_fee_cents`, and `office_action_round` — all default to 0, while `filed_at`, `published_at`, and `notice_of_allowance_at` are null until the corresponding transitions occur.

Goods and services are itemized against the draft. Each `GoodsServicesItem` is added under the application via its `application_id`, names the `nice_class_id` it is classified in, carries a `description` of the specific goods or services (non-empty, at most 500 characters), and a `pre_approved` flag (default false) that is true only when the identification is drawn verbatim from the office's ID Manual. Each item's `use_status` begins at `NOT_IN_USE`; for an intent-to-use application every item stays `NOT_IN_USE` and flips to `IN_USE` only when a Statement of Use is accepted. Whenever an item is added, the application's `class_count` is recomputed as the number of distinct `nice_class_id` values across its items.

### 3.2. Filing and Examination

Filing an application advances it from `DRAFT` to `FILED` and is the act that locks its fee. Before the transition is permitted, four substantive checks run, and their relative ordering matters because each carries a distinct error. They are evaluated in this order: first, the attorney-standing check — if the application names an attorney of record, that attorney's bar `status` must be `ACTIVE`, otherwise the filing is refused with `ERR_ATTORNEY_NOT_ACTIVE`; second, the foreign-representation check — if the applicant's `is_foreign_domiciled` is true, the `attorney_id` must be non-null, otherwise the filing is refused with `ERR_FOREIGN_REQUIRES_ATTORNEY`; third, the tier-compliance check — if the `filing_tier` is `TEAS_PLUS`, every `GoodsServicesItem` on the application must have `pre_approved` equal to true, otherwise the filing is refused with `ERR_TEAS_PLUS_REQUIRES_PREAPPROVED`; and fourth, the minimum-goods check — the application must carry at least one goods/services item, that is its `class_count` must be at least 1, otherwise the filing is refused with `ERR_NO_GOODS_SERVICES`. (These business checks run after the universal authentication, authorization, existence, ownership, and state checks described in §3.8.)

When all four pass, the server records `filed_at` as the current instant, computes and locks `filing_fee_cents`, and increments the owning applicant's `open_application_count` by one. The filing fee is locked at this moment and does not change if classes are amended afterward. The fee is tiered by application tier and class count: the per-class base amount is 25,000 cents for a `TEAS_PLUS` application and 35,000 cents for a `TEAS_STANDARD` application. For a `USE`-basis application the per-class amount is used as-is. For an `INTENT`-basis application — which reserves the mark before use — the per-class amount is increased by an intent surcharge of 10,000 cents before multiplication. The final `filing_fee_cents` is the resulting per-class amount multiplied by the `class_count`.

An examiner picks up a `FILED` application and assigns it for examination, moving it to `UNDER_EXAMINATION`. From `UNDER_EXAMINATION`, the examiner may issue an office action, refuse-free approve the mark for publication, or (for the relevant basis) register or allow it; these branches are detailed below.

### 3.3. Office Actions and the Examination Loop

While an application is `UNDER_EXAMINATION`, an examiner may issue an `OfficeAction` against it, which moves the application to `OFFICE_ACTION_ISSUED`. Creating the action requires the target `application_id`, a refusal `ground` — one of `LIKELIHOOD_OF_CONFUSION`, `MERELY_DESCRIPTIVE`, `SPECIMEN_DEFECT`, or `IDENTIFICATION_INDEFINITE` — and an optional `is_final` flag (default false), where a second substantive action on the same ground is marked final. The server assigns the action a `round_number` equal to the application's current `office_action_round` plus one (so the first action is round 1, the second round 2, and so on), stamps `issued_at` at the current instant, sets the action's `status` to `OUTSTANDING`, and computes its `response_deadline` as `issued_at` plus the 90-day response period. Issuing the action increments the application's `office_action_round` by one and, in the same operation, creates a docket deadline of subject type `OFFICE_ACTION` keyed to the office action's `id`, with `due_at` equal to the action's `response_deadline` and `status` of `PENDING`.

Responding to an outstanding office action returns the application from `OFFICE_ACTION_ISSUED` to `UNDER_EXAMINATION`, forming the examination revision loop in which a fresh examination may then issue yet another action. A response names the `office_action_id` it answers, carries the substantive `argument_text` (non-empty), and an optional `amends_identification` flag (default false) that is true when the response narrows the goods/services identification to overcome the refusal. The response may be filed only while the latest office action's `status` is `OUTSTANDING`; a response submitted against an action already advanced past `OUTSTANDING` is refused with `ERR_ACTION_ALREADY_CLOSED`.

Timeliness of a response depends on the action's finality, and this is the precise boundary split. The server stamps `submitted_at` and computes `days_late` as the number of whole days by which submission overran the deadline — formally, the larger of zero and the partial-day difference between `submitted_at` and the action's `response_deadline` rounded up to the next whole day — so `days_late` is 0 when the response arrives on or before the deadline. For a final action, any submission after the `response_deadline` is refused with `ERR_RESPONSE_DEADLINE_PASSED`. For a non-final action, a late submission is accepted as long as the current instant is within the 30-day grace tail after the deadline, and is refused with `ERR_RESPONSE_DEADLINE_PASSED` only once that tail has elapsed. Accepting a response sets the answered office action's `status` to `RESPONDED` and marks its docket deadline `MET`.

If an outstanding action is never answered, the application is abandoned. A system sweep against an `OUTSTANDING` action whose finality-adjusted grace tail has fully elapsed — that is, the current instant has reached the `response_deadline` plus 30 days for a non-final action, or plus zero days for a final action — sets the action's `status` to `EXPIRED`, marks its docket deadline `MISSED`, moves the application from `OFFICE_ACTION_ISSUED` to the terminal `ABANDONED` state, and decrements the owning applicant's `open_application_count` by one.

### 3.4. Publication, Allowance, Statement of Use, and Registration

From `UNDER_EXAMINATION`, when no office action on the application remains `OUTSTANDING`, an examiner approves the mark for publication, moving it to `PUBLISHED`. The server stamps `published_at` at the current instant and creates a docket deadline of subject type `OPPOSITION_WINDOW` keyed to the application's `id`, with `due_at` equal to `published_at` plus the 30-day opposition window and `status` of `PENDING`. Publication opens that mark to third-party challenge for the duration of the window.

Publication forks by filing basis. A `USE`-basis application is registered directly from publication: an examiner registers it, moving it from `PUBLISHED` to the terminal `REGISTERED` state, provided no board proceeding targeting this application is still live — that is, no `TTABProceeding` with this application as its target has a `claim_status` of `PLEADED` or `TRIAL`. An `INTENT`-basis application instead receives a Notice of Allowance: an examiner issues allowance, moving it from `PUBLISHED` to `ALLOWED`, again only if no targeting proceeding has a `claim_status` of `PLEADED` or `TRIAL`. Issuing allowance stamps `notice_of_allowance_at` and creates a docket deadline of subject type `SOU` keyed to the application's `id`, with `due_at` equal to `notice_of_allowance_at` plus the 180-day initial Statement-of-Use window and `status` of `PENDING`.

An allowed intent application must allege use before it can register. A `StatementOfUse` is filed against the application by its `application_id`, carrying a `specimen_url` (non-empty) evidencing the mark in commerce, a `first_use_date`, and an `extension_number` (an integer from 0 to 5, default 0) — 0 for a statement filed in the initial six-month window, otherwise the ordinal of the granted extension request the statement is filed under. A statement may be filed only for an `INTENT`-basis application in `ALLOWED` status, and the `extension_number` must not exceed the application's granted-extension count; a violation of either condition is refused with `ERR_SOU_NOT_PERMITTED`. As described in §2.6, the create also requires `expected_application_version` and is rejected with `ERR_STALE_VERSION` on a version mismatch. A freshly filed statement has `status` `SUBMITTED`; filing it increments the application's `version` by one, which is precisely what causes a later stale-version statement create to be rejected.

An examiner accepts a submitted statement, which registers the mark: the transition moves the application from `ALLOWED` to `REGISTERED` and requires that a `StatementOfUse` for the application currently be in `SUBMITTED` status. Acceptance sets that statement's `status` to `ACCEPTED`, flips every `GoodsServicesItem.use_status` on the application to `IN_USE`, and marks the application's `SOU` docket deadline `MET`.

Whenever an application matures into a `Registration` — whether by direct registration of a use application or by acceptance of a statement of use — the server mints the registration with `status` `ACTIVE`, a `maintenance_cycle` of 0, a server-assigned `registration_number` unique across all registrations, and `registered_at` set to the current instant, which anchors all subsequent §8/§9 maintenance windows. It computes the registration's `next_maintenance_due_at` (see §3.5) and creates a docket deadline of subject type `MAINTENANCE` keyed to the registration's `id` with `due_at` equal to that due date. When the registration arises from direct registration of a use application, the server additionally cancels any still-`PENDING` `OPPOSITION_WINDOW` docket deadline for that application.

If an allowed application never perfects use, it lapses. A system sweep against an `ALLOWED` application whose outer Statement-of-Use limit has elapsed — the current instant has reached `notice_of_allowance_at` plus the 1260-day maximum — and for which no `StatementOfUse` has reached `ACCEPTED`, marks the application's `SOU` docket deadline `MISSED`, moves the application from `ALLOWED` to the terminal `ABANDONED` state, and decrements the owning applicant's `open_application_count` by one.

### 3.5. Registration Maintenance: §8 and §9 Renewal Cycles

A registration must be periodically maintained or it falls out of force. Maintenance windows are all anchored to `registered_at`. The first window, a §8 declaration of continued use, closes at six years after registration. Every renewal window thereafter — a combined §8 and §9 filing — closes at a further ten years out; concretely, with the count of accepted maintenance filings taken after the acceptance in question, the next due date is six years after `registered_at` when that count is 0, and six plus ten times that count years after `registered_at` for each subsequent cycle. Every window opens one year before it closes, so a registration's current window opens at `next_maintenance_due_at` minus one year. A filing submitted before that opening instant is premature and refused with `ERR_MAINTENANCE_WINDOW_NOT_OPEN`. The registration's computed `next_maintenance_due_at` reflects the deadline of the next required filing and becomes null once the registration is cancelled or expired.

A `MaintenanceFiling` is filed against a registration by its `registration_id`, naming a `filing_type` of either `SECTION_8` (a standalone declaration of continued use) or `SECTION_8_AND_9` (the combined declaration-and-renewal due at each ten-year mark). As described in §2.6, the create requires `expected_registration_version` and is rejected with `ERR_STALE_VERSION` on mismatch; on success it sets the filing's `status` to `SUBMITTED`, stamps `filed_at`, and increments the registration's `version`. The server derives `in_grace_period`, true exactly when `filed_at` falls strictly after `next_maintenance_due_at` and on or before `next_maintenance_due_at` plus the 180-day grace window, which triggers a grace surcharge.

The filing's `fee_cents` is computed from the per-class fees over the distinct `nice_class_id` count of the registration's underlying application. The base is 22,500 cents per class for the §8 component; when the `filing_type` is `SECTION_8_AND_9`, a further 30,000 cents per class for the §9 component is added to the base. When the filing is in the grace period, a surcharge of 10,000 cents per class is added; a timely (non-grace) filing carries no surcharge. The `fee_cents` is the base plus any surcharge.

Acceptance of a maintenance filing is performed by an examiner and revisits the `ACTIVE` state from either direction. A timely filing — one whose `in_grace_period` is false, accepted while the registration is `ACTIVE` and the filing is `SUBMITTED` — keeps the registration `ACTIVE`. A grace filing — one whose `in_grace_period` is true, accepted while the registration is in `GRACE`, the filing is `SUBMITTED`, and the current instant is still within `next_maintenance_due_at` plus the 180-day grace window — moves the registration from `GRACE` back to `ACTIVE`. In both cases acceptance sets the filing's `status` to `ACCEPTED`, increments the registration's `maintenance_cycle` by one, recomputes `next_maintenance_due_at` for the new cycle, and — when `next_maintenance_due_at` is not null — creates a fresh `MAINTENANCE` docket deadline at the new due date. A timely acceptance additionally marks the prior `MAINTENANCE` docket deadline `MET`.

When a maintenance window closes with no accepted filing, a system sweep moves the registration from `ACTIVE` to `GRACE`, valid only once the current instant is past `next_maintenance_due_at` and no maintenance filing for the current cycle has been accepted; the sweep marks the current `MAINTENANCE` docket deadline `MISSED`. If the grace window then elapses — the current instant passes `next_maintenance_due_at` plus the 180-day grace window — a further system sweep moves the registration from `GRACE` to the terminal `EXPIRED` state and sets its `next_maintenance_due_at` to null.

### 3.6. Board Proceedings: Opposition and Cancellation

Third parties attack marks through the Trademark Trial and Appeal Board. A `TTABProceeding` is instituted by an applicant or attorney, naming the `proceeding_type` — `OPPOSITION` (against a published application) or `CANCELLATION` (against a registered mark) — the `petitioner_applicant_id` of the party bringing it, and exactly one target. An opposition requires a non-null `target_application_id` whose application is currently `PUBLISHED`; a cancellation requires a non-null `target_registration_id` whose registration is currently `ACTIVE` or `GRACE`. A target of the wrong kind or in a non-challengeable state is refused with `ERR_PROCEEDING_TARGET_INVALID`. An opposition additionally must be filed while the current instant is on or before the target application's `published_at` plus the 30-day opposition window; an opposition filed after that window has closed is refused with `ERR_OPPOSITION_WINDOW_CLOSED`.

Every proceeding tracks two independent dimensions. The `claim_status` (the petitioner's pleading) begins at `PLEADED` and may reach `TRIAL`, `SUSTAINED`, `DISMISSED`, or `WITHDRAWN`. The `defense_status` (the defendant's answer) begins at `AWAITING_ANSWER` and may reach `ANSWERED` or `DEFAULTED`. The two advance independently of one another. On institution the server stamps `filed_at`, computes `answer_deadline` as `filed_at` plus the 40-day answer period, and creates a docket deadline of subject type `OPPOSITION_ANSWER` keyed to the proceeding's `id`.

The defendant answers, moving `defense_status` from `AWAITING_ANSWER` to `ANSWERED`. An answer is permitted only while `defense_status` is `AWAITING_ANSWER`, the current instant is on or before the `answer_deadline`, and the `claim_status` is `PLEADED` or `TRIAL`; an answer attempted against a proceeding whose `defense_status` is no longer `AWAITING_ANSWER` is refused with `ERR_ACTION_ALREADY_CLOSED`. Answering marks the `OPPOSITION_ANSWER` docket deadline `MET`.

If the answer deadline passes unanswered, a clerk enters default, moving `defense_status` from `AWAITING_ANSWER` to `DEFAULTED`, valid only once the current instant is past the `answer_deadline`. Entering default marks the `OPPOSITION_ANSWER` docket deadline `MISSED` and, because default is a judgment for the petitioner, sets the `claim_status` to `SUSTAINED` and cascades to the attacked mark: for an opposition, the targeted application's `status` becomes `ABANDONED` and that applicant's `open_application_count` is decremented by one; for a cancellation, the targeted registration's `status` becomes `CANCELLED` and its `next_maintenance_due_at` is set to null.

When a proceeding has been answered, a clerk may set it for trial, moving `claim_status` from `PLEADED` to `TRIAL`, permitted only when `claim_status` is `PLEADED` and `defense_status` is `ANSWERED`. From trial, the clerk decides the case by supplying a `decision` in the request. A decision of `SUSTAIN` moves `claim_status` from `TRIAL` to `SUSTAINED` and cascades exactly as a default judgment does: an opposition abandons the targeted application and decrements its applicant's `open_application_count`; a cancellation cancels the targeted registration and nulls its `next_maintenance_due_at`, and additionally — this is the central-attack cascade — for every `MadridApplication` whose basic application is the cancelled registration's underlying application, and for which the current instant is still before that international application's `dependency_end_at`, the international application's `status` is set to `CEASED`. A decision of `DISMISS` moves `claim_status` from `TRIAL` to `DISMISSED` with no cascade; the attacked mark survives untouched.

A petitioner may also withdraw a pleaded proceeding, moving `claim_status` from `PLEADED` to `WITHDRAWN`, which cancels any still-`PENDING` `OPPOSITION_ANSWER` docket deadline for the proceeding. Every proceeding transition increments the proceeding's `version`.

### 3.7. Madrid International Applications, Risk Scoring, and the Docket

International protection rides on a domestic mark. A `MadridApplication` is created by an applicant or attorney, naming the `basic_application_id` of the underlying US application it is based on and a `designated_countries` array of ISO-3166 two-uppercase-letter codes naming the territories where protection is sought. The array must be non-empty, free of duplicates, and must not include `US`; a violation is refused with `ERR_MADRID_COUNTRIES_INVALID`. On creation the server computes `dependency_end_at` as the basic application's `filed_at` plus the 5-year dependency period — the span during which a successful central attack on the basic mark cascades a ceasing of the international registration — and sets the application's `status` to `PENDING_CERTIFICATION`.

An examiner certifies the international application, moving it from `PENDING_CERTIFICATION` to `CERTIFIED`, permitted only when the basic application is in any of `FILED`, `UNDER_EXAMINATION`, `OFFICE_ACTION_ISSUED`, `PUBLISHED`, `ALLOWED`, or `REGISTERED`. Certification computes and sets `fee_cents` as the Madrid base of 65,300 cents plus a per-designated-country component of 10,000 cents multiplied by the number of entries in `designated_countries`. A certified application is then forwarded by an examiner to the international bureau, moving it from `CERTIFIED` to the terminal `FORWARDED_TO_WIPO` state. Separately, the central-attack cascade described in §3.6 can move an international application in any of `PENDING_CERTIFICATION`, `CERTIFIED`, or `FORWARDED_TO_WIPO` into the terminal `CEASED` state when the basic mark is cancelled while the current instant is still before `dependency_end_at`; this ceasing has no endpoint of its own and is reached only as a side effect of a sustained cancellation. Every Madrid transition increments the application's `version`.

The applicant's **prosecution risk score** is computed on demand. The snapshot variant sums weighted counts over the applicant's portfolio: 15 points for each `OfficeAction` with `status` `OUTSTANDING` across the applicant's applications, plus 10 points for each `OfficeActionResponse` with `days_late` greater than 0, plus 40 points for each `TTABProceeding` whose `defense_status` is `DEFAULTED` where the targeted mark belongs to this applicant, plus 20 points for each `Registration` with `status` `GRACE` owned by the applicant through its application. The resulting total is capped at a ceiling of 100, so the reported score is the smaller of 100 and the accumulated total. The endpoint reports this as the snapshot variant by default. When the caller requests the projected variant by passing `include_pending_deadlines` as true, the computation additionally adds 15 points for each `PENDING` `DocketDeadline` whose `due_at` is already before the current instant — a deadline blown but not yet swept to `MISSED` — modeling imminent abandonment risk. The response carries the `applicant_id`, the integer `risk_score`, and the `variant` applied.

The unified docket is queryable throughout. Deadlines roll up to an application through their `application_id` for application-scoped listing, while maintenance deadlines roll up to their registration. Across the whole lifecycle, every window-opening transition writes a `PENDING` deadline and every resolving transition marks it `MET`, `MISSED`, or `CANCELLED`, so the docket always reflects the live state of every statutory clock.

### 3.8. The Universal Validation Order

Every mutating request runs a fixed gauntlet before any business rule specific to the operation is consulted, and the order is significant because each stage shadows the next. First, authentication: the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted for the operation, else `ERR_UNAUTHORIZED`. Third, existence: every resource id in the path, then every body foreign key, must resolve, validated in that left-to-right order, else `ERR_NOT_FOUND`. Fourth, ownership: for an entity-backed acting role, `X-User-ID` must own the targeted resource, else `ERR_NOT_RESOURCE_OWNER`. Fifth, state: the target resource must be in a state from which the requested transition is permitted, else `ERR_INVALID_STATE`. Sixth, the already-closed guard: a duplicate trigger on a resource already advanced past the step in question — such as responding to an office action no longer `OUTSTANDING`, or answering a proceeding no longer `AWAITING_ANSWER` — yields `ERR_ACTION_ALREADY_CLOSED`. This guard is evaluated against the status of the operative child resource the transition acts on (for an office-action response, the targeted office action's `status`; for an answer, the proceeding's `defense_status`), and for these two operations it is checked ahead of the fifth-stage state check on the parent: if that child resource has already advanced past the triggering step, `ERR_ACTION_ALREADY_CLOSED` is returned even when the parent's own state has meanwhile moved on (for instance, after a first office-action response has already returned the application to `UNDER_EXAMINATION`, a second response yields `ERR_ACTION_ALREADY_CLOSED` rather than `ERR_INVALID_STATE`). Seventh, the optimistic-concurrency check on the two supersede-style creates, yielding `ERR_STALE_VERSION`. Only after all of these do the operation-specific business checks of §3.2 through §3.7 run. A request whose body is malformed in a basic way — a missing required field, an unrecognized enum value, or a type mismatch — is rejected with `ERR_VALIDATION`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that transition or otherwise modify an existing resource return `200 OK`. The two exceptions worth noting are direct registration of a use application and acceptance of a statement of use: each mints a brand-new `Registration` resource and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register a trademark owner | Attorney, Applicant |
| GET | `/applicants/{id}` | Fetch an applicant | Attorney, Applicant, Examiner, TTABClerk |
| GET | `/applicants/{id}/risk-score` | Computed prosecution risk score (snapshot or projected) | Attorney, Examiner |
| POST | `/attorneys` | Register a prosecuting attorney | Attorney |
| GET | `/attorneys/{id}` | Fetch an attorney | Attorney, Examiner, TTABClerk |
| POST | `/attorneys/{id}/suspend` | Mark an attorney suspended | Examiner |
| POST | `/nice-classes` | Seed a Nice class code | Examiner |
| GET | `/nice-classes/{id}` | Fetch a Nice class | Attorney, Applicant, Examiner, TTABClerk |
| GET | `/nice-classes/{id}/goods-services` | List goods/services filed under a Nice class | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/applications` | Create a draft application | Attorney, Applicant |
| GET | `/applications/{id}` | Fetch an application | Attorney, Applicant, Examiner, TTABClerk |
| GET | `/applications` | Filtered list of applications | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/applications/{id}/goods-services` | Add a goods/services item | Attorney, Applicant |
| GET | `/applications/{id}/goods-services` | List goods/services of an application | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/applications/{id}/file` | File the application | Attorney, Applicant |
| POST | `/applications/{id}/assign-examination` | Assign to an examiner | Examiner |
| POST | `/applications/{id}/approve-publication` | Approve for publication | Examiner |
| POST | `/applications/{id}/issue-allowance` | Issue Notice of Allowance (intent) | Examiner |
| POST | `/applications/{id}/register` | Register a use application from publication | Examiner |
| POST | `/applications/{id}/abandon-sou-lapsed` | Abandon an allowed application whose SOU period lapsed | Examiner |
| GET | `/applications/{id}/docket-deadlines` | List docket deadlines rolled up to an application | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/office-actions` | Issue an office action | Examiner |
| GET | `/office-actions/{id}` | Fetch an office action | Attorney, Applicant, Examiner |
| GET | `/applications/{id}/office-actions` | List office actions of an application | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/office-actions/{id}/expire` | Sweep an outstanding action to abandonment | Examiner |
| POST | `/office-action-responses` | Submit a response to the outstanding office action | Attorney, Applicant |
| GET | `/office-actions/{id}/responses` | List responses to an office action | Attorney, Applicant, Examiner |
| POST | `/statements-of-use` | File a Statement of Use (OCC-guarded) | Attorney, Applicant |
| POST | `/statements-of-use/{id}/accept` | Examiner accepts the SOU | Examiner |
| GET | `/applications/{id}/statements-of-use` | List statements of use of an application | Attorney, Applicant, Examiner |
| POST | `/ttab-proceedings` | Institute an opposition or cancellation | Attorney, Applicant |
| GET | `/ttab-proceedings/{id}` | Fetch a proceeding | Attorney, Applicant, Examiner, TTABClerk |
| GET | `/ttab-proceedings` | Filtered list of proceedings | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/ttab-proceedings/{id}/answer` | Defendant files an answer | Attorney, Applicant |
| POST | `/ttab-proceedings/{id}/enter-default` | Clerk enters default | TTABClerk |
| POST | `/ttab-proceedings/{id}/set-for-trial` | Clerk sets proceeding for trial | TTABClerk |
| POST | `/ttab-proceedings/{id}/decide` | Clerk decides the proceeding | TTABClerk |
| POST | `/ttab-proceedings/{id}/withdraw` | Petitioner withdraws | Attorney, Applicant |
| GET | `/registrations/{id}` | Fetch a registration | Attorney, Applicant, Examiner, TTABClerk |
| GET | `/applications/{id}/registration` | Find the registration of an application | Attorney, Applicant, Examiner, TTABClerk |
| POST | `/registrations/{id}/enter-grace` | Move a registration to grace | Examiner |
| POST | `/registrations/{id}/expire` | Expire a registration whose grace window elapsed | Examiner |
| POST | `/maintenance-filings` | File a §8 or §8&9 maintenance filing (OCC-guarded) | Attorney, Applicant |
| POST | `/maintenance-filings/{id}/accept` | Examiner accepts a maintenance filing | Examiner |
| GET | `/registrations/{id}/maintenance-filings` | List maintenance filings of a registration | Attorney, Applicant, Examiner |
| POST | `/madrid-applications` | Create an international application | Attorney, Applicant |
| GET | `/madrid-applications/{id}` | Fetch a Madrid application | Attorney, Applicant, Examiner |
| POST | `/madrid-applications/{id}/certify` | Examiner certifies the international application | Examiner |
| POST | `/madrid-applications/{id}/forward` | Forward certified application to the bureau | Examiner |
| GET | `/applications/{id}/madrid-applications` | List Madrid applications based on an application | Attorney, Applicant, Examiner |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | Examiner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACTION_ALREADY_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ATTORNEY_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_FOREIGN_REQUIRES_ATTORNEY` | 422 Unprocessable Entity |
| `ERR_TEAS_PLUS_REQUIRES_PREAPPROVED` | 422 Unprocessable Entity |
| `ERR_NO_GOODS_SERVICES` | 422 Unprocessable Entity |
| `ERR_PROCEEDING_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_OPPOSITION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_SOU_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_MAINTENANCE_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_MADRID_COUNTRIES_INVALID` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_DUPLICATE_BAR_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_NICE_CLASS` | 409 Conflict |
