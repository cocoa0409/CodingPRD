# Email Marketing Automation API — Product Requirements Document

## 1. Introduction

Email service providers live or die on two numbers: the reputation of the addresses they send from, and the trust of the people who receive the mail. A marketer who imports a purchased list, mails an unconfirmed contact, or forgets a one-click unsubscribe link does not merely annoy a recipient — they degrade the sending reputation of every other tenant on the platform and expose the business to regulatory liability. This document specifies the Email Marketing Automation API, a multi-tenant service that governs the whole chain from list building and consent capture, through campaign authoring, compliance review and scheduled dispatch, to delivery telemetry, engagement analytics and contact-tier invoicing.

The product is deliberately opinionated about consent. Every contact carries an auditable record of how consent was obtained; audiences may demand a double-opt-in confirmation before a contact is mailable; and any address that unsubscribes, hard-bounces, or files a spam complaint is written into an account-wide suppression list from which it can never be quietly re-added. Compliance is not advisory: a campaign cannot leave review without a published template that embeds a working unsubscribe link, and the operator who wrote the campaign is never the operator who signs it off.

The API is equally opinionated about money and capacity. Send credits are granted once, reserved at schedule time, and either consumed on completion or returned on cancellation, so that the grant always reconciles against the sum of the balance, the reservations and the consumption. Dispatches are priced at the moment they are scheduled — never re-priced afterwards — using the recipient count and the account's deliverability reputation as it stood at that instant. Invoices are driven by the *peak* contact count observed inside a billing period, not the count that happens to survive to the end of it. Because the system is exercised deterministically by tests and by operations tooling, all time is read from a server-controlled logical clock rather than wall-clock time, and all background work (opt-in expiry, campaign dispatch, journey advancement, billing close) is driven by an explicit operations epoch rather than by a hidden scheduler.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries an `X-User-Role` header naming the capacity in which the caller acts. Every request except those made as `Anonymous` additionally carries an `X-User-ID` header identifying the acting principal. A request whose `X-User-Role` is missing or names something other than one of the four declared roles, or whose `X-User-ID` is missing for any role other than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose claimed role is well-formed but is not among the roles the target operation admits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles are `PlatformAdmin`, `CampaignAuthor`, `ComplianceApprover`, and `Anonymous`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform operator provisions tenants and their staff, drives the logical clock and the operations epoch, and injects delivery telemetry from the sending infrastructure. The server does not compare a `PlatformAdmin` identifier to any entity's `id`, and a `PlatformAdmin` is not scoped to any single tenant.
- When `X-User-Role` is `CampaignAuthor`, `X-User-ID` is the `id` of the acting `AccountUser`; ownership checks on any resource that references an `AccountUser` compare the resource's foreign-key field to `X-User-ID`, and tenant checks compare that `AccountUser`'s `account_id` to the owning account of every resource named in the path or the body.
- When `X-User-Role` is `ComplianceApprover`, `X-User-ID` is likewise the `id` of the acting `AccountUser`, and the same ownership and tenant comparisons apply.
- When `X-User-Role` is `Anonymous`, no `X-User-ID` is sent at all. `Anonymous` is the unauthenticated visitor filling in a public signup form or clicking a link inside a delivered email; it has no persisted identity and the server never resolves it to an entity.

For the two entity-backed roles, the identifier in `X-User-ID` must name an existing `AccountUser` whose `user_role` permits the claimed header. An `AccountUser` whose `user_role` is `CAMPAIGN_AUTHOR` may claim only `CampaignAuthor`; one whose `user_role` is `COMPLIANCE_APPROVER` may claim only `ComplianceApprover`; one whose `user_role` is `DUAL` may claim either. Any other combination — an unknown identifier, or a role the operator's `user_role` does not permit — is rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403).

Tenant isolation is absolute for the two entity-backed roles: a `CampaignAuthor` or `ComplianceApprover` whose own `AccountUser.account_id` differs from the owning account of any resource they touch — the account behind a path identifier, an `account_id` in the body, the account owning a referenced template, or the account owning the audience behind an audience identifier — is rejected with `ERR_CROSS_ACCOUNT_ACCESS` (HTTP 403). `PlatformAdmin` is exempt from this check.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` is the number of items to skip and defaults to 0. A `limit` outside that range, a negative `offset`, or either parameter supplied as something that is not an integer is rejected with `ERR_INVALID_REQUEST`; neither is ever silently clamped. Unless a specific endpoint states otherwise, list results are sorted by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` counts the items matching the filter before pagination is applied and `has_more` reports whether any item remains beyond the returned page.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the row first appeared.

Mutable resources — `Account`, `AccountUser`, `Audience`, `Subscriber`, `ImportJob`, `Segment`, `Template`, `Campaign`, `Send`, `Journey`, `JourneyEnrollment` and `BillingCycle` — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by exactly one on every mutation of that resource. Recomputation of a derived field counts as a mutation of the resource that stores it: when a subscriber's arrival changes an audience's `subscriber_count`, that audience's `updated_at` and `version` move too.

`SuppressionEntry` is the sole exception. Suppression records are immutable once written: they carry only `id` and `created_at`, and have neither `updated_at` nor `version`.

All timestamps that the business logic reasons about — `scheduled_at`, `consent_confirmed_at`, `unsubscribed_at`, `delivered_at`, `first_opened_at`, `last_clicked_at`, `last_opened_at`, `enrolled_at`, `next_action_at`, `closed_at`, `winner_selected_at`, `period_start` and `period_end` — are read from the server's **logical clock**, never from wall-clock time. The logical clock starts at exactly `2026-05-01T00:00:00Z` and stays there until a platform operator moves it; it may be moved forward or backward, and the operation that moves it takes a single `to_iso8601` instant and answers with the new `current_utc`. No entity is mutated by moving the clock.

### 2.5. Order of Request Validation

When several rules could reject the same request, the rule that fires is always the earliest one in the following sequence. Implementations must not report a later failure while an earlier one is also true.

1. Authentication of the headers — `ERR_UNAUTHENTICATED`.
2. The claimed role is admitted by the operation — `ERR_FORBIDDEN_ROLE`.
3. For `CampaignAuthor` and `ComplianceApprover`, the identifier resolves to an `AccountUser` whose `user_role` permits the claimed role — `ERR_ROLE_IDENTITY_MISMATCH`.
4. Body shape: required fields present, enum values legal, integers inside their declared ranges, `rows` between 1 and 100 elements, `variant_b_subject` supplied whenever `ab_test_enabled` is true, and a well-formed `steps` array of 1 to 10 elements whose `step_index` values run from 0 upward in ascending order, each equal to the element's own position in the array — `ERR_INVALID_REQUEST`. Only the fields an operation declares are read: every other key in the body — an unknown name, or a server-owned field such as `id`, `version`, `consent_state`, `engagement_score` or `subscriber_count` — is silently ignored rather than rejected, so a `POST /audiences/{id}/subscribers` that carries `consent_state` or `engagement_score` still succeeds and the server's own values stand. The forward-only branch-target rule on a journey's `steps` is evaluated at this same stage, ahead of every later rule, and a violation of it is reported as `ERR_JOURNEY_STEP_ORDER`.
5. Path identifiers resolve, left to right, the leftmost miss winning — `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`, `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate. A request for a nested resource under a parent that does not exist reports the parent's miss, not the child's.
6. Body foreign keys resolve — the same not-found family plus `ERR_SEGMENT_NOT_FOUND`, applying to account creation of audiences, template creation, campaign creation, journey creation, and event injection.
7. Tenant isolation — `ERR_CROSS_ACCOUNT_ACCESS`.
8. Segregation of duties on a campaign review decision — `ERR_SEGREGATION_OF_DUTIES`.
9. A campaign's optional segment belongs to the campaign's own audience — `ERR_SEGMENT_AUDIENCE_MISMATCH`.
10. Optimistic concurrency on the parent record — `ERR_STALE_VERSION`.
11. The generic state guard: the requested transition exists from the resource's current state — `ERR_INVALID_STATE`.
12. Then the specific business rules, in this order: `ERR_CAMPAIGN_NOT_APPROVED`, `ERR_ALREADY_UNSUBSCRIBED`, `ERR_IMPORT_NOT_ROLLBACKABLE`, `ERR_ACCOUNT_SUSPENDED`, `ERR_TEMPLATE_NOT_PUBLISHED`, `ERR_MISSING_UNSUBSCRIBE_LINK`, `ERR_EMAIL_SUPPRESSED`, the consent-token checks (`ERR_INVALID_CONFIRMATION_TOKEN` and `ERR_INVALID_UNSUBSCRIBE_TOKEN`), `ERR_SUBSCRIBER_EXISTS`, `ERR_CONFIRMATION_EXPIRED`, `ERR_SCHEDULE_IN_PAST`, `ERR_AUDIENCE_FATIGUE_CONFLICT`, `ERR_SEND_CAPACITY_EXCEEDED`, `ERR_JOURNEY_TEMPLATE_INVALID`, `ERR_CLICK_WITHOUT_OPEN`, `ERR_AB_NOT_ENABLED`, `ERR_INSUFFICIENT_AB_SAMPLE`, `ERR_EMPTY_RECIPIENT_SET`, and finally `ERR_INSUFFICIENT_SEND_CREDITS`.

Two consequences of this ordering are worth spelling out, because they are easy to get backwards. On a campaign schedule request the account's suspension is checked before any of the temporal, fatigue, capacity, recipient or credit rules, so a suspended account never learns whether its schedule would otherwise have been affordable. And on that same request the credit check is dead last: a schedule that is simultaneously in the past and unaffordable reports `ERR_SCHEDULE_IN_PAST`.

### 2.6. Optimistic Concurrency on Parent Records

Two write operations debit or re-shape a parent record that the client must have observed before it acted, and both are guarded by an optimistic-concurrency check against that parent's `version`.

Scheduling a campaign requires `expected_account_version` in the request body, carrying the `version` of the owning `Account` as the client last read it. If that value does not equal the account's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because scheduling debits `Account.send_credit_balance`: a client acting on a stale view of the account may be reserving credits that another writer has already spent. Two different `APPROVED` campaigns may each legitimately be scheduled, so no state precondition rejects the second request — only the stale-version check does.

Creating an import job requires `expected_audience_version` in the request body, carrying the `version` of the target `Audience` as the client last read it. A mismatch with the audience's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Importing the same rows twice is a legitimate operation the product allows, so again no state precondition catches it; the guard catches the client that computed its row set from a `subscriber_count` that is no longer true.

Both fields are non-optional on their operations. No other endpoint accepts an expected-version field, and none is inferred where it is not asked for.

### 2.7. The Send-Credit Ledger

Send credits are granted exactly once, when the tenant is provisioned, and never again. `granted_send_credits` records that immutable grant. From it, three buckets are derived and must always reconcile: `send_credit_balance` holds credits that are neither reserved nor spent; `reserved_send_credits` is the sum of `reserved_credit_count` across the account's campaigns whose `status` is `SCHEDULED` or `SENDING`; and `consumed_send_credits` is the sum of `reserved_credit_count` across the account's campaigns whose `status` is `SENT`. At every observable instant, `granted_send_credits` equals the balance plus the reservations plus the consumption.

Only campaign dispatch touches credits. Emails minted by an automation journey are included in the plan and never move any of the three buckets.

### 2.8. Money, Scores and Rounding Discipline

All money in this system is expressed in whole cents as integers — `base_fee_cents`, `overage_cents`, `total_cents`, and `send_charge_cents` are never fractional. Intermediate arithmetic may be fractional, but every value that lands on a resource is rounded **half up** to a whole cent, and the *place* in the arithmetic where that rounding happens is pinned by the rule that produces it; rounding earlier or later than specified produces a different, wrong number. The same discipline governs the two 0–100 scores, `sender_reputation_score` and the pair `engagement_score` / `engagement_score_90d`: each is rounded half up to a whole number once and then clamped into the range 0 through 100 inclusive, so that a raw value below 0 becomes 0 and a raw value above 100 becomes 100. Counts — `subscriber_count`, `member_count`, `recipient_count`, `peak_contact_count`, `row_count` and the import dispositions — are integers and are never rounded.

### 2.9. CAN-SPAM, Consent and the Account Suppression List

Consent is the spine of the product. A `Subscriber` records where consent came from in `consent_source`, one of `SIGNUP_FORM`, `IMPORT`, `API` or `MANUAL`, and where it currently stands in `consent_state`, one of `PENDING`, `CONFIRMED`, `UNSUBSCRIBED`, `CLEANED` or `ARCHIVED`. `CLEANED` and `ARCHIVED` are terminal.

Suppression is account-wide, not audience-wide. A `SuppressionEntry` names an `account_id`, an `email`, and a `reason` of `UNSUBSCRIBE`, `HARD_BOUNCE` or `COMPLAINT`. Once an address is suppressed for an account, no further subscriber with that address may be created in *any* audience of that account, and the address is silently withheld from every future recipient snapshot of that account. At most one suppression row exists per account-and-address pair: whenever a cascade would create a second, the existing row is left as it is and no duplicate is written.

Compliance is enforced at approval time rather than at template publication. A template becomes mailable only through a review that verifies both that it is `PUBLISHED` and that its `html_body` embeds the literal merge tag `{{unsubscribe_url}}`, which is exactly what `has_unsubscribe_link` records. That merge tag renders, per recipient, into a one-click unsubscribe link keyed on the subscriber's `unsubscribe_token`.

### 2.10. Deliverability Reputation and Automatic Suspension

Each account carries a `sender_reputation_score` between 0 and 100 inclusive, which prices its dispatches and, at the extreme, shuts its sending down. The score considers only *scored* sends — the account's sends, campaign and journey alike, whose `delivery_status` is `DELIVERED`, `SOFT_BOUNCED`, `HARD_BOUNCED` or `COMPLAINED`. Sends that are `QUEUED`, `SUPPRESSED` or `CANCELLED` count in neither the numerator nor the denominator of anything on this page. An account with no scored sends scores 100.

Otherwise, take the percentage of scored sends that are `HARD_BOUNCED`, the percentage that are `COMPLAINED`, and the percentage that are `SOFT_BOUNCED`, each expressed on a 0-to-100 scale. Start from 100, subtract two times the hard-bounce percentage, subtract three times the complaint percentage, and subtract one half of the soft-bounce percentage. Round that raw value half up to a whole number and clamp it into 0 through 100. The score is recomputed on every event that changes any send's `delivery_status`.

Immediately after the score is recomputed, the suspension threshold is evaluated on the same event. If the account has **at least four** scored sends and the share of those scored sends that are `HARD_BOUNCED` is **at least 0.25**, the account's `status` moves from `ACTIVE` to `SUSPENDED` and its `suspension_reason` is set to `HIGH_HARD_BOUNCE_RATE`. Both comparisons are inclusive: exactly four scored sends of which exactly one hard-bounced (a rate of 0.25) *does* suspend the account, while five scored sends of which one hard-bounced (a rate of 0.20) does not. While an account is `SUSPENDED`, its `status` is `SUSPENDED`, `suspension_reason` is non-null, its scheduled campaigns are no longer dispatched by the operations epoch and remain `SCHEDULED`, and any attempt to schedule a further campaign is refused with `ERR_ACCOUNT_SUSPENDED`. While an account is `ACTIVE`, `suspension_reason` is null.

### 2.11. The Operations Epoch

Nothing in this system happens on a hidden timer. Opt-in windows expire, campaigns dispatch, journey enrollments advance and billing periods close only when a platform operator advances the **operations epoch**, and each advance runs five phases in this pinned order:

1. Archive every `PENDING` subscriber whose confirmation window has expired.
2. Dispatch every `SCHEDULED` campaign of an `ACTIVE` account whose `scheduled_at` is at or before the clock, processing campaigns in ascending `scheduled_at` order and breaking ties by ascending `created_at`, minting one send per position of the frozen recipient snapshot.
3. Advance every due, `ACTIVE` enrollment of an `ACTIVE` journey, processing enrollments in ascending `created_at` order.
4. Snapshot each account's current `billable_contact_count` into that account's `OPEN` billing cycle.
5. Close every `OPEN` billing cycle whose `period_end` is at or before the clock and roll a fresh one forward, repeating until the account's open cycle ends strictly after the clock.

The epoch reports what it did: `subscribers_archived`, `campaigns_dispatched`, `sends_created`, `enrollments_advanced` and `billing_cycles_closed`. `sends_created` counts every send the epoch minted — campaign sends, the `SUPPRESSED` ones included, and journey-step emails alike — and `enrollments_advanced` counts every due enrollment the third phase picked up, including one that the consent re-check retired to `SUPPRESSED` without executing a step.

## 3. Business Logic & Workflows

### 3.1. Tenant Provisioning and the Send-Credit Grant

A platform operator provisions a tenant by supplying a `name` of 1 to 120 characters and, optionally, a `plan_tier`, an `initial_send_credits` grant and an `hourly_send_capacity`. `plan_tier` is one of `FREE`, `ESSENTIALS`, `STANDARD` or `PREMIUM` and defaults to `FREE`. `hourly_send_capacity` is the largest number of recipients the account may hold inside any one overlapping group of send windows; it must be at least 1 and defaults to 1000. The grant is optional and defaults to 0; whatever is supplied is copied into `granted_send_credits`, which never changes again, and into `send_credit_balance`, which does. A freshly provisioned account is `ACTIVE` with a null `suspension_reason` and a `sender_reputation_score` of 100, and its `billable_contact_count`, `reserved_send_credits` and `consumed_send_credits` all start at zero.

Provisioning also opens the tenant's first billing period: a cycle whose `period_start` is the current clock instant, whose `period_end` is exactly 30 days later, whose `status` is `OPEN`, and whose `peak_contact_count` starts at 0. `tier_applied` is null while the cycle is `OPEN`, and `base_fee_cents`, `overage_cents` and `total_cents` all read 0 until it closes; `closed_at` is null.

Operators inside the tenant are created by the platform operator with an `email` containing an `@` character and unique within the account — a repeat address inside the same account is refused with `ERR_INVALID_REQUEST` — and a `user_role` of `CAMPAIGN_AUTHOR`, `COMPLIANCE_APPROVER` or `DUAL`, which decides which `X-User-Role` headers that person may later claim. Reading an account back returns its `version` — and clients that intend to schedule a campaign are expected to read the account first precisely to capture that number.

### 3.2. Consent Capture and the Subscriber Lifecycle

An audience is a list. It belongs to an account, carries a `name` of 1 to 120 characters, a `default_from_email` containing an `@` character that campaigns targeting the list will send from, and a `double_optin_required` flag that defaults to true. Its `subscriber_count` is derived, never supplied: it counts the audience's subscribers whose `consent_state` is `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`. Contacts that are `CLEANED` or `ARCHIVED` fall out of that count. Unsubscribed contacts, notably, stay in it — they still occupy a slot on the list, and the business bills for them.

Adding a single contact — the public signup form, an authoring tool, or a platform operator all use the same capability — takes an `email` containing an `@` character, a `consent_source`, and an optional `first_name` that defaults to null and is available to merge tags. Two guards run before the row is written: if the address matches a suppression entry of the audience's account, the request is refused with `ERR_EMAIL_SUPPRESSED`, and if a subscriber with that address already exists in that audience in *any* `consent_state` at all, it is refused with `ERR_SUBSCRIBER_EXISTS`. Suppression is checked first.

The new contact is minted with an `unsubscribe_token`, a stable value that is never rotated for the lifetime of the row and which the `{{unsubscribe_url}}` merge tag resolves against. Where the audience requires double opt-in, the contact lands in `PENDING`, a `confirmation_token` is minted alongside, and `consent_confirmed_at` is null. Where the audience does not require double opt-in, the contact is minted directly into `CONFIRMED` inside the very same request: `confirmation_token` stays null, `consent_confirmed_at` is stamped with the clock, and — because a subscriber just became `CONFIRMED` — the subscribe-triggered journey enrollments described in §3.10 fire immediately. Either way, `unsubscribed_at` and `last_opened_at` are null, `delivered_send_count`, `opened_send_count` and `clicked_send_count` are 0, `engagement_state` is `NEW`, and both `engagement_score` and `engagement_score_90d` read 50. The audience's `subscriber_count` and the account's `billable_contact_count` are both recomputed.

Confirmation is an anonymous act: the recipient clicks the link in the opt-in email, and the request carries the `confirmation_token` it was issued. The contact must still be in `PENDING`, or the request is refused with `ERR_INVALID_STATE`; the supplied token must equal the stored `confirmation_token`, or the request is refused with `ERR_INVALID_CONFIRMATION_TOKEN`; and the clock must read strictly earlier than 48 hours after the contact's `created_at`, or the request is refused with `ERR_CONFIRMATION_EXPIRED` and the contact stays exactly where it was, in `PENDING`. On success `PENDING → CONFIRMED`: `consent_confirmed_at` is stamped, `confirmation_token` is cleared to null, subscribe-triggered journey enrollments fire, and `subscriber_count` does not move, because a `PENDING` contact was already being counted.

An opt-in that is never confirmed does not linger. During the first phase of the operations epoch, every contact still in `PENDING` whose `created_at` is 48 hours or more behind the clock moves `PENDING → ARCHIVED`, its `confirmation_token` is cleared, and both `subscriber_count` and `billable_contact_count` fall accordingly. The 48-hour window is thus enforced twice, from both ends: a late confirmation is rejected, and a stale pending row is swept.

Unsubscribing is likewise an anonymous act driven by a one-click link, and the request carries the `unsubscribe_token`. The contact must be in `PENDING` or `CONFIRMED` — any other `consent_state` is refused with `ERR_ALREADY_UNSUBSCRIBED` — and the supplied token must equal the stored one, or the request is refused with `ERR_INVALID_UNSUBSCRIBE_TOKEN`. On success the contact moves to `UNSUBSCRIBED` from whichever of `PENDING` or `CONFIRMED` it was in, `unsubscribed_at` is stamped with the clock, and a suppression entry with `reason` `UNSUBSCRIBE` is written for the account and address unless one already exists for that pair. `subscriber_count` is deliberately untouched: an `UNSUBSCRIBED` contact remains billable. Existing journey enrollments are not disturbed here either; as §3.10 explains, they are retired lazily, the next time they come due.

A `CampaignAuthor` may unsubscribe a contact on the contact's behalf; nobody may re-subscribe one, because the suppression entry now blocks the address across every audience of the account.

### 3.3. Bulk Import and Its Compensating Rollback

Bulk import is where the consent rules get their hardest workout. A `CampaignAuthor` submits `rows` — an ordered array of between 1 and 100 objects, each carrying an `email` and an optional `first_name` — together with the `expected_audience_version` demanded by §2.6. The job runs synchronously inside the request and comes back already finished; there is no polling.

Rows are processed **strictly in array order**, and each row is subjected to three checks in this pinned sequence. First format: if the row's `email` is absent, is not a string, or contains no `@` character, the row is counted into `rejected_count` and processing moves to the next row — a malformed row never fails the whole request, and a `first_name` that is not a string is not a rejection either, it is simply read as null. Second suppression: if the address matches a suppression entry of the audience's account, the row is counted into `suppressed_count` and skipped — suppression beats duplication, and an address that is both suppressed and already present on the list is reported as suppressed, not as a duplicate. Third duplication: if the address was already accepted by an earlier row of this same job, or a subscriber with that address already exists in this audience in any `consent_state`, the row is counted into `duplicate_count` and skipped. A row that survives all three creates a subscriber with `consent_source` stamped `IMPORT`, landing in `CONFIRMED` when the audience does not require double opt-in and in `PENDING` (with a `confirmation_token`) when it does, and is counted into `accepted_count`.

`row_count` is the length of the submitted array, and the four dispositions always reconcile against it: `accepted_count` plus `rejected_count` plus `duplicate_count` plus `suppressed_count` equals `row_count` on every job, without exception. `created_subscriber_ids` lists the ids the job created, in row order, and the job echoes the submitted array back verbatim on its own `rows` field.

The job's `status` is decided by the arithmetic: `COMPLETED` when `accepted_count` equals `row_count`, `REJECTED` when `accepted_count` is 0, and `PARTIAL` otherwise. All three outcomes are successful requests that increment the audience's `version` by one; even a `REJECTED` job, which creates nothing and leaves `created_subscriber_ids` empty, still burns the version, so a client that retries after a rejection must re-read the audience first. On the two outcomes that created rows, `subscriber_count` and `billable_contact_count` are recomputed.

Rollback is the compensating action. A `CampaignAuthor` may roll back a job whose `status` is `COMPLETED` or `PARTIAL`, provided that no send has ever been minted for any subscriber in `created_subscriber_ids`; a job in any other status, or one whose contacts have already been mailed, is refused with `ERR_IMPORT_NOT_ROLLBACKABLE`. A successful rollback moves the job to `ROLLED_BACK` and archives exactly the rows the job created: every subscriber in `created_subscriber_ids` whose `consent_state` is not already `ARCHIVED` transitions to `ARCHIVED`, whether it currently sits in `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`. Because those contacts have left the counted set, the audience's `subscriber_count` is recomputed from its formula, and because that changed, the account's `billable_contact_count` is recomputed from its formula in turn — restoring the pre-import contact count. `ROLLED_BACK` and `REJECTED` are terminal for a job.

### 3.4. Segments and Engagement Scoring

A segment is a saved filter over one audience. It carries a `name` of 1 to 120 characters, a non-empty `consent_states` array drawn from `PENDING`, `CONFIRMED` and `UNSUBSCRIBED` — `CLEANED` and `ARCHIVED` are not admissible values, so a cleaned or archived contact can never qualify for any segment — a `min_engagement_score` between 0 and 100, and an optional `max_days_since_open` that defaults to null and, when present, must be at least 0.

A subscriber is a member of a segment when it belongs to the segment's own audience, its `consent_state` is one of the values listed in `consent_states`, its `engagement_score` is greater than or equal to `min_engagement_score` (the comparison is inclusive, so a score exactly equal to the floor qualifies), and — when `max_days_since_open` is not null — its `last_opened_at` is not null and the whole number of days between `last_opened_at` and the clock, computed by discarding any fractional remainder, is less than or equal to `max_days_since_open`. A contact that has never opened anything fails the recency clause whenever `max_days_since_open` is set, and passes vacuously when it is null. `member_count` is the size of that member set and is recomputed on every read of the segment and every time a campaign freezes its recipients.

The `engagement_score` that segmentation leans on is one of two variants of the same weighted formula, differing only in which sends enter the input set. Only sends whose `delivery_status` is `DELIVERED` are ever considered; queued, bounced, suppressed, complained and cancelled sends are excluded from numerator and denominator alike. The `LIFETIME` variant, stored on `engagement_score`, admits every delivered send the contact has ever received. The `ROLLING_90D` variant, stored on `engagement_score_90d`, admits only sends whose `delivered_at` falls on or after the instant 90 days before the clock, and its recency term therefore sees only opens inside that window; a contact who clicked four months ago and merely opened last week can score 70 on the lifetime variant and 40 on the rolling one from identical data.

Within a variant, if the input set is empty, the score is 50 — the neutral value of an unmeasured contact. Otherwise, let the open count be the number of sends in the set whose `engagement_status` is `OPENED` or `CLICKED`, and the click count be the number whose `engagement_status` is `CLICKED`. Divide each by the size of the set to get an open rate and a click rate. The base is 100 multiplied by the sum of four tenths of the open rate and six tenths of the click rate. The recency multiplier looks at the latest `first_opened_at` across the sends in the set: it is 1.0 when the whole number of days between that instant and the clock is at most 30; 0.8 when that day count is greater than 30 and at most 90; and 0.5 when it exceeds 90 or when no send in the set has ever been opened. The volume bonus rewards a measured history: take the size of the set, subtract 2, floor the result at 0, multiply by 2, and cap the outcome at 10. Multiply the base by the recency multiplier, add the volume bonus, round the result half up to a whole number exactly once, and clamp it into 0 through 100.

`engagement_state` is derived from the lifetime score, with one override at the front: a contact whose `delivered_send_count` is 0 is `NEW` regardless of anything else. Otherwise the contact is `ENGAGED` when `engagement_score` is at least 70, `DORMANT` when it is at least 40 and below 70, and `LAPSED` when it is below 40. Alongside them the system maintains three read-only counters: `delivered_send_count` is the number of the contact's sends that are `DELIVERED`; `opened_send_count` is the number of those delivered sends whose `engagement_status` is `OPENED` or `CLICKED`; and `clicked_send_count` is the number whose `engagement_status` is `CLICKED`. `last_opened_at` records the most recent open-or-click instant across all of the contact's sends and stays null until the first one.

### 3.5. Templates and the Campaign Review Loop

A `CampaignAuthor` writes a template against their own account with a `name` of 1 to 120 characters, a `subject` of 1 to 200 characters and an `html_body` of 1 to 5000 characters. `has_unsubscribe_link` is not an input — it is derived, and reads true exactly when the literal substring `{{unsubscribe_url}}` occurs in `html_body`. A template is born in `DRAFT` and may be published once, moving `DRAFT → PUBLISHED`; publishing from any other state is refused with `ERR_INVALID_STATE`. `PUBLISHED` is terminal — templates are never edited in place — and publication deliberately does **not** check for the unsubscribe merge tag. A non-compliant template can therefore reach `PUBLISHED` quite legally; the CAN-SPAM gate sits one step later, on campaign approval.

A campaign names its `account_id`, the `audience_id` it targets, the `template_id` it will render, a `name` of 1 to 120 characters, and optionally a `segment_id` narrowing the audience. When a `segment_id` is supplied, the segment must belong to the very audience the campaign targets, or the creation is refused with `ERR_SEGMENT_AUDIENCE_MISMATCH`. A campaign may also opt into an A/B test with `ab_test_enabled`, which defaults to false; when it is true, `variant_b_subject` is required and `variant_split_pct` — the percentage of the recipient snapshot that receives variant `A`, an integer from 1 to 99 — defaults to 50. `created_by_user_id` is stamped from the acting `X-User-ID` and is never supplied by the client. The campaign is born in `DRAFT` with `approved_by_user_id`, `review_note`, `pinned_subject`, `pinned_html_body`, `pinned_template_version`, `scheduled_at`, `send_window_minutes`, `winning_variant` and `winner_selected_at` all null, `recipient_snapshot_ids` empty, and `recipient_count`, `reserved_credit_count` and `send_charge_cents` all 0.

The author submits the campaign for review, moving `DRAFT → IN_REVIEW`; a submission from any other state is refused with `ERR_INVALID_STATE`, and the acting operator must belong to the campaign's own account.

Review belongs exclusively to a `ComplianceApprover`, and it is where segregation of duties bites. The reviewer supplies a `decision` of either `APPROVE` or `REQUEST_CHANGES`, plus an optional `note` that is recorded into `review_note` either way. The campaign must be in `IN_REVIEW`, or the decision is refused with `ERR_INVALID_STATE`. The reviewer's `X-User-ID` must differ from the campaign's `created_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES` — and this holds even for an operator whose `user_role` is `DUAL` and who is therefore perfectly entitled to claim the `ComplianceApprover` header: authorship, not permission, is what disqualifies them.

On `APPROVE`, two CAN-SPAM checks run in order. The campaign's template must be `PUBLISHED`, or the decision is refused with `ERR_TEMPLATE_NOT_PUBLISHED`; and that template's `has_unsubscribe_link` must be true, or the decision is refused with `ERR_MISSING_UNSUBSCRIBE_LINK`. Passing both, the campaign moves `IN_REVIEW → APPROVED`, `approved_by_user_id` is stamped from the reviewer's `X-User-ID`, and the template is *pinned*: `pinned_subject` takes the template's `subject`, `pinned_html_body` takes its `html_body`, and `pinned_template_version` takes its `version`, freezing exactly what compliance signed off on.

On `REQUEST_CHANGES`, the campaign cycles back `IN_REVIEW → DRAFT`, `approved_by_user_id` is cleared to null, and all three pins — `pinned_subject`, `pinned_html_body` and `pinned_template_version` — are cleared to null as well. The revision loop is unbounded: the author may resubmit and the reviewer may re-decide any number of times, and each `APPROVE` re-pins from the template as it stands at that moment.

### 3.6. Scheduling a Dispatch

Scheduling is the busiest gate in the product. The author supplies `scheduled_at`, a `send_window_minutes` between 1 and 1440, and the `expected_account_version` of §2.6. The campaign must be in `APPROVED`, or the request is refused with `ERR_CAMPAIGN_NOT_APPROVED`. The account must be `ACTIVE`, or it is refused with `ERR_ACCOUNT_SUSPENDED`. `scheduled_at` must be strictly after the clock, or it is refused with `ERR_SCHEDULE_IN_PAST`.

Two capacity rules then run, the fatigue rule always before the window rule. **Audience fatigue** treats scheduled dispatches on the same list as point events: for every other campaign of the same `audience_id` whose `status` is `SCHEDULED` or `SENDING`, the absolute gap between its `scheduled_at` and this one must be at least 6 hours. A gap of strictly less than 6 hours is refused with `ERR_AUDIENCE_FATIGUE_CONFLICT`; a gap of exactly 6 hours is allowed. **Send-window capacity** treats dispatches on the same account as intervals: a campaign occupies the half-open interval that begins at its `scheduled_at` and ends `send_window_minutes` later, so two windows that merely touch end-to-end do not overlap. Sum `recipient_count` across every campaign of the account whose `status` is `SCHEDULED` or `SENDING` and whose window overlaps this campaign's window, add this campaign's own recipient count, and the total must not exceed `hourly_send_capacity`. A total strictly greater than the capacity is refused with `ERR_SEND_CAPACITY_EXCEEDED`; a total exactly equal to it passes. Campaigns in `DRAFT`, `IN_REVIEW`, `APPROVED`, `SENT` or `CANCELLED` occupy no window and contribute nothing to either rule.

The recipient snapshot is frozen at this moment, and its ordering is observable. Start from the subscribers of the campaign's audience whose `consent_state` is exactly `CONFIRMED` — and note that this filter is applied first and is not overridable, so a `PENDING` or `UNSUBSCRIBED` contact never receives a campaign email even when the campaign's segment lists those states as admissible. If a `segment_id` is set, intersect that pool with the segment's member set. Then drop every contact whose address matches a suppression entry of the campaign's account. Sort what remains by `created_at` ascending, breaking ties by `email` ascending — the subscriber's `id` never participates in the ordering — and store the resulting ids, in that order, into `recipient_snapshot_ids`. `recipient_count` is the length of that list. If it is 0, the whole request is refused with `ERR_EMPTY_RECIPIENT_SET`.

The dispatch is then priced into `send_charge_cents`, in four pinned steps. **Step one** picks a per-email rate keyed on the recipient count: 2.8 cents each when the count is 10 or fewer, 2.2 cents each when it is between 11 and 50 inclusive, and 1.6 cents each when it is 51 or more. Multiply the rate by the recipient count to obtain a raw subtotal, which stays fractional and is *not* rounded yet. **Step two** derives a volume discount from that raw, pre-surcharge subtotal — never from the campaign's final total, which would be circular: the discount is 0 percent when the raw subtotal is below 20 cents, 5 percent when it is at least 20 and below 40 cents, and 10 percent when it is 40 cents or more. Multiply the raw subtotal by that percentage and round the product half up to a whole cent to obtain the discount. **Step three** derives a reputation surcharge from the account's `sender_reputation_score` as it stands right now: 0 percent when the score is 90 or above, 5 percent when it is at least 70 and below 90, and 20 percent when it is below 70. Apply that percentage to the raw subtotal *minus the already-rounded discount*, and round the product half up to a whole cent. **Step four** assembles the charge: round the raw subtotal half up to a whole cent, subtract the discount, add the surcharge. Later movements in the account's reputation never re-price a campaign that is already scheduled.

Finally the credits. The account's `send_credit_balance` must be greater than or equal to the recipient count, or the request is refused with `ERR_INSUFFICIENT_SEND_CREDITS` — the last check to run, after everything above has passed. On success the campaign moves `APPROVED → SCHEDULED`: `reserved_credit_count` is set to the recipient count, the same amount is subtracted from `send_credit_balance`, `reserved_send_credits` is recomputed, and the account's `version` increments by one — which is exactly why the next schedule against the same account needs a freshly read `expected_account_version`.

Cancellation runs the reservation backwards. A `CampaignAuthor` of the campaign's own account may cancel a campaign whose `status` is `SCHEDULED` or `SENDING`; any other status is refused with `ERR_INVALID_STATE`. A campaign cancelled from `SCHEDULED` has minted no sends yet, so the cascade is short: `reserved_credit_count` drops to 0, that whole released amount is added back to `send_credit_balance`, `reserved_send_credits` is recomputed, and the account's `version` increments. A campaign cancelled from `SENDING` cascades further: because the campaign became `CANCELLED`, every one of its sends whose `delivery_status` is `QUEUED` or `SOFT_BOUNCED` transitions to `CANCELLED`, and such a send is thereafter excluded from every reputation and engagement denominator; because those sends were cancelled, the campaign releases its *whole original* reservation — `reserved_credit_count` drops to 0; because it dropped to 0, that entire released amount is added back to `send_credit_balance` and `reserved_send_credits` is recomputed; and the account's `version` increments. Sends that had already reached a terminal `delivery_status` — `DELIVERED`, `HARD_BOUNCED`, `SUPPRESSED` or `COMPLAINED` — are left exactly as they are, but the full original reservation is still returned. That is the stated compensation policy, and it is what keeps the grant reconciling against the three buckets. `scheduled_at` is retained on a cancelled campaign; `SENT` and `CANCELLED` are terminal.

### 3.7. Dispatch and the Two Dimensions of a Send

The second phase of the operations epoch dispatches. Every campaign in `SCHEDULED` whose `scheduled_at` is at or before the clock, and whose account is `ACTIVE`, moves `SCHEDULED → SENDING`; campaigns are taken in ascending `scheduled_at` order, ties broken by ascending `created_at`. A campaign belonging to a `SUSPENDED` account is passed over entirely — it stays in `SCHEDULED` and mints nothing, and will dispatch on a later epoch only if the account is restored.

Dispatch mints exactly one send per position of `recipient_snapshot_ids`, in snapshot order, each with the campaign's id in `campaign_id` and a null `journey_id`. Each send's initial `delivery_status` is decided per recipient: it is `SUPPRESSED` when that subscriber's `consent_state` is no longer exactly `CONFIRMED`, or when that subscriber's address now matches a suppression entry of the account — the snapshot was frozen at schedule time, and the world may have moved since — and it is `QUEUED` otherwise. `engagement_status` starts at `NOT_OPENED` for every send, and `soft_bounce_count`, `open_count` and `click_count` all start at 0, with `delivered_at`, `first_opened_at` and `last_clicked_at` null. When `ab_test_enabled` is true, `variant_label` is assigned over the snapshot order: multiply the recipient count by `variant_split_pct`, divide by 100, discard any fraction, and the first that many positions take label `A` while every remaining position takes label `B`. When the campaign is not an A/B test, `variant_label` is null on every send.

Each send then carries **two independent state dimensions on the same row**, and neither constrains the other beyond one gate. The `delivery_status` dimension starts at `QUEUED` and its terminal values are `DELIVERED`, `HARD_BOUNCED`, `SUPPRESSED`, `COMPLAINED` and `CANCELLED`; `SOFT_BOUNCED` is explicitly *not* terminal. The `engagement_status` dimension starts at `NOT_OPENED`, advances through `OPENED`, and terminates at `CLICKED`. The only coupling between them is that engagement events are only accepted on a send whose `delivery_status` is `DELIVERED`.

A campaign leaves `SENDING` by bubble-up rather than by any client action: the moment every send of the campaign has reached a terminal `delivery_status`, the campaign transitions `SENDING → SENT`. This is evaluated at the end of every epoch dispatch and at the end of every telemetry event that changes a send's `delivery_status`. A single `SOFT_BOUNCED` send is enough to hold the campaign in `SENDING` indefinitely. When the campaign reaches `SENT`, its `reserved_credit_count` is retained — the reservation is not released, it *moves*: `reserved_send_credits` and `consumed_send_credits` are both recomputed, so the amount migrates from the reserved bucket to the consumed bucket while `send_credit_balance` does not change.

### 3.8. Delivery Telemetry, Bounces and Complaints

The sending infrastructure reports back through a single telemetry capability available to platform operators, which names a `send_id` and a `kind` of `DELIVERED`, `SOFT_BOUNCE`, `HARD_BOUNCE`, `COMPLAINT`, `OPEN` or `CLICK`. An unknown `send_id` is refused with `ERR_SEND_NOT_FOUND`, and an event whose kind is not admissible from the send's current state is refused with `ERR_INVALID_STATE`.

A `DELIVERED` event is accepted on a send whose `delivery_status` is `QUEUED` or `SOFT_BOUNCED` — the second case being a retry that finally landed — and drives `QUEUED → DELIVERED` or `SOFT_BOUNCED → DELIVERED`. It stamps `delivered_at` with the clock, recomputes the account's `sender_reputation_score`, recomputes the subscriber's `engagement_score`, `engagement_score_90d` and `engagement_state`, and, if every send of the parent campaign is now terminal, bubbles the campaign to `SENT`.

A `SOFT_BOUNCE` event is accepted on a send whose `delivery_status` is `QUEUED` or `SOFT_BOUNCED` and increments `soft_bounce_count` by one. While the incremented count remains below 3, the send sits (or stays) in `SOFT_BOUNCED` — the transitions `QUEUED → SOFT_BOUNCED` and `SOFT_BOUNCED → SOFT_BOUNCED` — and the account's reputation is recomputed. On the increment that brings `soft_bounce_count` to 3, the send escalates `SOFT_BOUNCED → HARD_BOUNCED` and the full hard-bounce cascade below fires.

A `HARD_BOUNCE` event is accepted on a send whose `delivery_status` is `QUEUED` or `SOFT_BOUNCED` and drives it straight to `HARD_BOUNCED`. The cascade is four links long and every link must fire. Because the send hard-bounced, its subscriber's `consent_state` moves to `CLEANED` — from `CONFIRMED` or from `PENDING` alike, while a contact already sitting in `UNSUBSCRIBED`, `CLEANED` or `ARCHIVED` is left in the state it is in — and a suppression entry with `reason` `HARD_BOUNCE` is written for that account and address unless one already exists. Because the subscriber became `CLEANED`, the audience's `subscriber_count` is recomputed and falls. Because `subscriber_count` changed, the account's `billable_contact_count` is recomputed and falls with it. And the account's `sender_reputation_score` is recomputed and the suspension threshold of §2.10 evaluated on the same event, which is where an account with at least four scored sends and a hard-bounce share of at least 0.25 flips `ACTIVE → SUSPENDED` with `suspension_reason` `HIGH_HARD_BOUNCE_RATE`. If every send of the parent campaign is now terminal, the campaign bubbles to `SENT`.

A `COMPLAINT` event is accepted only on a send whose `delivery_status` is exactly `DELIVERED`, and drives `DELIVERED → COMPLAINED`. The send's `engagement_status` is left exactly as it was — a contact who opened, clicked and *then* complained keeps `CLICKED`, because the two dimensions genuinely do not constrain each other. The subscriber moves `CONFIRMED → UNSUBSCRIBED` with `unsubscribed_at` stamped — and is left exactly as it is when it is already in any other `consent_state` — a suppression entry with `reason` `COMPLAINT` is written unless one already exists for that account and address, and the account's `sender_reputation_score` is recomputed.

An `OPEN` event requires `delivery_status` to be `DELIVERED`. The first one drives `NOT_OPENED → OPENED`, increments `open_count` and stamps `first_opened_at`; a repeat open leaves the send in `OPENED`, increments `open_count` again and leaves `first_opened_at` alone. Either way the subscriber's `last_opened_at` is set to the clock and its two engagement scores and `engagement_state` are recomputed.

A `CLICK` event requires `delivery_status` to be `DELIVERED` and requires the send's `engagement_status` to already be `OPENED` or `CLICKED`; a click on a send still in `NOT_OPENED` is refused with `ERR_CLICK_WITHOUT_OPEN`. The first click drives `OPENED → CLICKED`, and a repeat click leaves the send in `CLICKED`; either way `click_count` increments, `last_clicked_at` and the subscriber's `last_opened_at` are stamped with the clock. On the first click — and only on the first, the one that actually moves `OPENED → CLICKED` — the click-triggered journey enrollments of §3.10 fire, and only when the click landed on a *campaign* send: a first click on a journey-minted send enrols nobody. The subscriber's engagement scores and `engagement_state`, by contrast, are recomputed on every `CLICK` event, repeat clicks included.

### 3.9. A/B Variants and Winner Selection

Once an A/B campaign has reached `SENT`, its author asks the system to name the winner. The campaign must be `SENT` and must not already carry a `winning_variant` — otherwise the request is refused with `ERR_INVALID_STATE` — and its `ab_test_enabled` must be true, or the request is refused with `ERR_AB_NOT_ENABLED`.

Only `DELIVERED` sends of the campaign enter the comparison, partitioned by `variant_label`. Bounced, suppressed, complained, cancelled and still-queued sends are excluded from both the sample gate and the rates. For each label, count the delivered sends, count how many of them have an `engagement_status` of `OPENED` or `CLICKED`, and count how many have an `engagement_status` of `CLICKED`. The sample gate then demands at least 2 delivered sends for label `A`, at least 2 for label `B`, and at least 1 open across the two labels combined; a campaign that fails any part of that gate is refused with `ERR_INSUFFICIENT_AB_SAMPLE` and no winner is recorded.

The winner is the label whose click rate — its click count divided by its delivered-send count — is strictly higher; the comparison is made on the exact rational values, with no rounding beforehand. A tie on click rate is broken in favour of the label with the higher open rate, computed the same way. A tie on both is broken in favour of the label whose earliest send has the smaller `created_at`; the send's `id` never participates. The chosen label is written to `winning_variant` and `winner_selected_at` is stamped with the clock.

### 3.10. Automation Journeys and Enrollment Advancement

A journey is an automation that walks a contact through a list of steps. It names its `account_id` and the `audience_id` whose contacts may enrol, a `name` of 1 to 120 characters, a `trigger_event`, and a `steps` array of 1 to 10 elements. Each step object carries a `step_index` and a `kind`; the indexes run 0 through one less than the number of steps, in ascending order. A `WAIT` step carries `wait_hours`, a non-negative integer; an `EMAIL` step carries a non-empty `template_id` string, whose existence and publication are not examined until the journey is activated; a `CONDITION` step carries a `condition_min_score` between 0 and 100 together with an `on_true_step_index` and an `on_false_step_index`, both integers. Both branch targets must be **strictly greater** than the branching step's own `step_index` — the graph is forward-only, so no enrollment can loop — and a journey whose steps violate that is refused at creation with `ERR_JOURNEY_STEP_ORDER`. A journey is born in `DRAFT` with `active_enrollment_count` and `entered_count` at 0.

Activation moves a journey `DRAFT → ACTIVE` or, on a later pass, `PAUSED → ACTIVE`; activating an already-`ACTIVE` journey is refused with `ERR_INVALID_STATE`. Every step whose `kind` is `EMAIL` must reference a template that is `PUBLISHED` and belongs to the journey's own account, or activation is refused with `ERR_JOURNEY_TEMPLATE_INVALID` — and a `template_id` that names no template at all is refused the same way, never with `ERR_TEMPLATE_NOT_FOUND`. Activation never back-fills: only contacts that confirm, or click, *after* the journey went active will ever enrol. Reactivating a paused journey does not shift any enrollment's `next_action_at`; the enrollments simply become eligible again.

Pausing moves a journey `ACTIVE → PAUSED`, and pausing anything not `ACTIVE` is refused with `ERR_INVALID_STATE`. While paused, no trigger creates a new enrollment, and existing enrollments keep their `ACTIVE` status but are skipped by the operations epoch. The cycle between `ACTIVE` and `PAUSED` may repeat without bound.

Enrollment is triggered by one of two events, named by `trigger_event`. `SUBSCRIBE_CONFIRMED` enrols a contact at the instant its `consent_state` becomes `CONFIRMED` — whether that happened inside a single-opt-in create or through an explicit double-opt-in confirmation. `CAMPAIGN_CLICK` enrols a contact on the first click applied to one of that contact's campaign sends. In both cases the rule is the same: for every journey that is `ACTIVE`, whose `audience_id` matches the contact's audience, whose `trigger_event` matches the event, and which has no `ACTIVE` enrollment for that contact already, an enrollment is created with `status` `ACTIVE`, `current_step_index` 0, `next_action_at` set to the clock and `enrolled_at` set to the clock, carrying the `journey_id` and the `subscriber_id`. Because an enrollment appeared, that journey's `active_enrollment_count` and `entered_count` are both recomputed — `active_enrollment_count` counting the journey's `ACTIVE` enrollments and `entered_count` counting all of its enrollments across every status.

The third phase of the operations epoch advances enrollments, taking them in ascending `created_at` order. An enrollment is due when its journey is `ACTIVE` and its `next_action_at` is at or before the clock. Before anything is executed, the contact's consent is re-checked: if the subscriber's `consent_state` is anything other than `CONFIRMED` — `UNSUBSCRIBED`, `CLEANED`, `ARCHIVED` or even back to `PENDING` — the enrollment moves `ACTIVE → SUPPRESSED`, no email is minted, the current step is not executed, and `active_enrollment_count` is recomputed. This is the lazy retirement promised in §3.2: an unsubscribe does not touch enrollments at the moment it happens, it simply guarantees that the enrollment dies the next time it comes due.

For a still-consenting contact, steps are executed from `current_step_index` onward. A `WAIT` step sets `next_action_at` to the clock plus `wait_hours`, advances `current_step_index` by one, and **stops** the enrollment for this epoch. An `EMAIL` step mints a send carrying the journey's id in `journey_id`, a null `campaign_id`, the `subscriber_id`, `delivery_status` `QUEUED`, `engagement_status` `NOT_OPENED` and a null `variant_label`; it advances `current_step_index` by one and **continues** to the next step within the same epoch. A `CONDITION` step compares the subscriber's `engagement_score` against `condition_min_score`: when the score is greater than or equal to the threshold, `current_step_index` is set to `on_true_step_index`, otherwise to `on_false_step_index`; either way it **continues**. When `current_step_index` has advanced past the last step — or has been branched onto an index that no step occupies — the enrollment moves `ACTIVE → COMPLETED` and `active_enrollment_count` is recomputed. An enrollment that leaves `ACTIVE`, whether to `COMPLETED` or to `SUPPRESSED`, keeps the `next_action_at` it last carried; the field is not cleared. Journey emails are included in the plan: they never touch `send_credit_balance`, `reserved_send_credits` or `consumed_send_credits`, though they *do* count as scored sends for the account's reputation once they are delivered or bounce.

### 3.11. Contact-Tier Billing

Billing is driven by the *peak* number of contacts an account carried inside a period, not by the number that happen to survive to its end. The fourth phase of every operations epoch samples the account's current `billable_contact_count` into its `OPEN` billing cycle, keeping the larger of the sample and the cycle's existing `peak_contact_count`. That count is monotone within a cycle: a list that swelled to 13 contacts and then collapsed to 0 is still invoiced on 13. The account's `billable_contact_count` itself is the sum, across all of the account's audiences, of each audience's `subscriber_count` — that is, of the contacts whose `consent_state` is `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`. It is recomputed on every mutation that changes any subscriber's consent state: a create, a confirmation, an unsubscribe, a hard-bounce cleaning, an opt-in expiry, an import, or an import rollback. A cycle opened at provisioning starts its peak at 0; a cycle opened by a close-and-roll starts its peak at the account's billable contact count at the moment of the close.

The fifth phase closes. Every `OPEN` cycle whose `period_end` is at or before the clock moves `OPEN → CLOSED`: `tier_applied` freezes the account's `plan_tier` as it stands at that instant, `closed_at` is stamped with the clock, and the invoice is computed. A fresh cycle is then opened whose `period_start` is the closed cycle's `period_end`, whose `period_end` is 30 days after that, and whose `peak_contact_count` starts at the account's billable contact count at close time. The close-and-roll repeats until the account's open cycle ends strictly after the clock, so an epoch that jumps the clock forward by a quarter of a year closes several cycles in one pass.

The invoice has two parts. `base_fee_cents` is the flat fee of the frozen tier: 0 cents on `FREE`, 1300 cents on `ESSENTIALS`, 2000 cents on `STANDARD`, and 29900 cents on `PREMIUM`. `overage_cents` charges for the contacts beyond what the tier includes. Each tier includes a number of contacts — 2 on `FREE`, 5 on `ESSENTIALS`, 10 on `STANDARD` and 25 on `PREMIUM` — and grants a discount on every overage charge: none on `FREE`, 10 percent on `ESSENTIALS`, 20 percent on `STANDARD` and 30 percent on `PREMIUM`.

Subtract the tier's included contacts from the cycle's `peak_contact_count` and floor the result at zero to get the overage contacts. Those contacts are then charged in **blocks of 5**, counting from the first block: divide the overage contacts by 5 and round *up* to a whole number to learn how many blocks there are, where the last block may be partly filled and is charged only for the contacts it actually holds. The first and second blocks are charged at 27.0 cents per contact; the third, fourth and fifth blocks at 19.0 cents per contact; every block from the sixth onward at 13.0 cents per contact. **The rounding order is pinned: each block's amount — its contact count, times its rate, times one minus the tier's discount — is rounded half up to whole cents on its own, and only then are the block amounts summed into `overage_cents`.** Summing the raw block amounts and rounding once at the end is the wrong reading and produces a different invoice. `total_cents` is `base_fee_cents` plus `overage_cents`. The only input to the overage is the cycle's `peak_contact_count`; the account's `billable_contact_count` at close time is never used for it.

## 4. Endpoint Definitions

All endpoints are mounted at the root of the service. Creating a new resource answers with HTTP 201; every other successful operation, including state transitions that modify an existing resource, answers with HTTP 200. Request and response bodies are governed by §2.2 and by the narratives of §3 — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/accounts` | Create a tenant and open its first billing cycle | PlatformAdmin |
| GET | `/accounts/{id}` | Read one account, including its credit buckets, contact count, reputation and version | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/accounts/{id}/users` | Create an operator of the account | PlatformAdmin |
| GET | `/accounts/{id}/users` | List the operators of an account | PlatformAdmin |
| GET | `/accounts/{id}/billing-cycles` | List the account's billing cycles, ordered by `period_start` ascending | PlatformAdmin, CampaignAuthor |
| GET | `/accounts/{id}/suppressions` | List the account-wide suppression list | PlatformAdmin, CampaignAuthor |
| POST | `/audiences` | Create an audience (list) | PlatformAdmin, CampaignAuthor |
| GET | `/audiences/{id}` | Read one audience, including its subscriber count and version | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/audiences` | List audiences, filterable by account | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/audiences/{id}/subscribers` | Add one contact to the audience | Anonymous, CampaignAuthor, PlatformAdmin |
| GET | `/subscribers/{id}` | Read one contact, including its tokens and both engagement-score variants | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/subscribers` | List contacts, filterable by audience and state | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/subscribers/{id}/confirm` | Double-opt-in confirmation | Anonymous |
| POST | `/subscribers/{id}/unsubscribe` | One-click unsubscribe | Anonymous, CampaignAuthor |
| GET | `/subscribers/{id}/enrollments` | List this contact's journey enrollments | PlatformAdmin, CampaignAuthor |
| POST | `/audiences/{id}/import-jobs` | Bulk-import rows into the audience; runs synchronously | CampaignAuthor |
| GET | `/audiences/{id}/import-jobs` | List the audience's import jobs | PlatformAdmin, CampaignAuthor |
| POST | `/import-jobs/{id}/rollback` | Compensating rollback of an import | CampaignAuthor |
| POST | `/audiences/{id}/segments` | Create a dynamic segment over the audience | CampaignAuthor, PlatformAdmin |
| GET | `/audiences/{id}/segments` | List the audience's segments with a freshly recomputed member count | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/templates` | Create an email template in `DRAFT` | CampaignAuthor |
| POST | `/templates/{id}/publish` | Publish a template | CampaignAuthor |
| GET | `/templates/{id}` | Read one template | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/templates` | List templates, filterable by account and status | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/campaigns` | Create a campaign in `DRAFT` | CampaignAuthor |
| GET | `/campaigns/{id}` | Read one campaign, including its snapshot, charge, pins and winner | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/campaigns` | List campaigns | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/campaigns/{id}/submit-review` | Submit a campaign for compliance review | CampaignAuthor |
| POST | `/campaigns/{id}/review` | Decide a campaign review | ComplianceApprover |
| POST | `/campaigns/{id}/schedule` | Schedule a dispatch: freeze recipients, price it, reserve credits | CampaignAuthor |
| POST | `/campaigns/{id}/cancel` | Cancel a scheduled or sending campaign | CampaignAuthor |
| POST | `/campaigns/{id}/select-winner` | Record the A/B winner on a sent campaign | CampaignAuthor |
| GET | `/sends/{id}` | Read one send, including both state dimensions and its counters | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/sends` | List sends | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/journeys` | Create an automation journey in `DRAFT` with its full step list | CampaignAuthor |
| GET | `/journeys/{id}` | Read one journey, including its enrollment counters | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| GET | `/journeys` | List journeys | PlatformAdmin, CampaignAuthor, ComplianceApprover |
| POST | `/journeys/{id}/activate` | Activate a draft or paused journey | CampaignAuthor |
| POST | `/journeys/{id}/pause` | Pause an active journey | CampaignAuthor |
| GET | `/journeys/{id}/enrollments` | List this journey's enrollments | PlatformAdmin, CampaignAuthor |
| POST | `/_clock/set_current_utc` | Move the logical clock to the supplied `to_iso8601` instant | PlatformAdmin |
| POST | `/_ops/run` | Advance the operations epoch through its five phases | PlatformAdmin |
| POST | `/_events/emit` | Inject a delivery-infrastructure event against one send | PlatformAdmin |

List endpoints accept `limit` and `offset`. Beyond those, the account-user, billing-cycle, import-job, segment and enrollment lists filter on `status` where they have one; the suppression list filters on `email` and `reason`; the audience, template and journey lists filter on `account_id`; the journey list also filters on `audience_id`; the subscriber list filters on `audience_id`, `consent_state` and `engagement_state`; the campaign list filters on `account_id`, `audience_id`, `segment_id`, `template_id`, `created_by_user_id`, `approved_by_user_id` and `status`; and the send list filters on `campaign_id`, `journey_id`, `subscriber_id`, `variant_label`, `delivery_status` and `engagement_status`. Filters are query parameters, not path or body identifiers, so tenant isolation never rejects one: a `CampaignAuthor` or `ComplianceApprover` sees every list silently restricted to their own account, and a filter naming another account's resource simply yields an empty page rather than `ERR_CROSS_ACCOUNT_ACCESS`. A query parameter an endpoint does not declare is ignored.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_ROLE_IDENTITY_MISMATCH` | 403 |
| `ERR_CROSS_ACCOUNT_ACCESS` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_AUDIENCE_NOT_FOUND` | 404 |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 |
| `ERR_TEMPLATE_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_SEGMENT_NOT_FOUND` | 404 |
| `ERR_JOURNEY_NOT_FOUND` | 404 |
| `ERR_IMPORT_JOB_NOT_FOUND` | 404 |
| `ERR_SEND_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 403 |
| `ERR_CAMPAIGN_NOT_APPROVED` | 409 |
| `ERR_ALREADY_UNSUBSCRIBED` | 409 |
| `ERR_SUBSCRIBER_EXISTS` | 409 |
| `ERR_IMPORT_NOT_ROLLBACKABLE` | 409 |
| `ERR_MISSING_UNSUBSCRIBE_LINK` | 422 |
| `ERR_TEMPLATE_NOT_PUBLISHED` | 422 |
| `ERR_EMAIL_SUPPRESSED` | 409 |
| `ERR_SEGMENT_AUDIENCE_MISMATCH` | 422 |
| `ERR_SCHEDULE_IN_PAST` | 422 |
| `ERR_AUDIENCE_FATIGUE_CONFLICT` | 409 |
| `ERR_CONFIRMATION_EXPIRED` | 422 |
| `ERR_INVALID_CONFIRMATION_TOKEN` | 403 |
| `ERR_INVALID_UNSUBSCRIBE_TOKEN` | 403 |
| `ERR_SEND_CAPACITY_EXCEEDED` | 409 |
| `ERR_EMPTY_RECIPIENT_SET` | 422 |
| `ERR_INSUFFICIENT_AB_SAMPLE` | 422 |
| `ERR_AB_NOT_ENABLED` | 422 |
| `ERR_JOURNEY_STEP_ORDER` | 422 |
| `ERR_JOURNEY_TEMPLATE_INVALID` | 422 |
| `ERR_CLICK_WITHOUT_OPEN` | 422 |
| `ERR_INSUFFICIENT_SEND_CREDITS` | 402 |
