# Emergency-Alert API — Product Requirements Document

## 1. Introduction

Public-safety agencies increasingly depend on mass-notification platforms to reach residents the moment a hazard emerges — a flash flood, a chemical spill, a boil-water advisory, or a scheduled evacuation drill. This document specifies the Emergency-Alert API, a CodeRED/Everbridge-style backbone for building and maintaining a resident contact database, capturing per-channel opt-in consent, composing and approving alerts, targeting recipients by group membership or geographic proximity, fanning notifications out across SMS, voice, email, and IPAWS gateways, and tracking each message all the way through delivery, acknowledgement, and retry.

The platform is built around a deliberate separation of duties. A resident's contact record and its individual delivery channels are curated by administrators, but consent to be contacted on any given channel belongs to the resident. Alerts are drafted and dispatched by operators who may never approve their own work; a second, independent reviewer must sign off before a single message leaves the building. Layered on top are the operational realities of real notification traffic: accessibility guarantees for deaf and hard-of-hearing recipients, per-gateway throttling to protect downstream carriers, multilingual message bodies, quiet-hours preferences, retry back-off after transient failures, and integration hooks that let computer-aided-dispatch (CAD) and weather feeds seed alerts automatically.

Because timing governs almost every rule in this domain — delivery windows, retry back-off, throttle windows, maintenance blackouts, and drill scheduling — the system runs on an explicit, server-controlled logical clock rather than wall-clock time. Every temporal decision in the specification below is evaluated against that clock, which an operational integrator advances deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelope formats, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Dispatcher`, `Approver`, `ContactAdmin`, `Contact`, and `Integrator`.

- A `Dispatcher` composes alerts, adds localizations and targeting, submits for approval, previews recipients, dispatches, cancels, and closes. `X-User-ID` for a `Dispatcher` is an opaque operator identifier not tied to any persisted entity. The server records it as `author_user_id` on any alert the dispatcher composes, but it does not compare it to any entity's `id` other than for the segregation-of-duties check described in §3.4.
- An `Approver` approves or rejects alerts that a dispatcher has submitted. `X-User-ID` for an `Approver` is likewise an opaque operator identifier; the server compares it to the target alert's `author_user_id` to enforce segregation of duties but never treats it as an entity `id`.
- A `ContactAdmin` curates contacts, channels, groups, subscriptions, templates, gateways, maintenance windows, and drills. `X-User-ID` for a `ContactAdmin` is an opaque operator identifier not tied to any persisted entity.
- A `Contact` is a resident acting on their own resources. This role is entity-backed: when `X-User-Role` is `Contact`, `X-User-ID` is the `id` of the acting `Contact`. Ownership checks compare the relevant foreign key on the target resource — a channel's `contact_id`, a subscription's `contact_id`, or a notification's `contact_id` — to `X-User-ID`.
- An `Integrator` is the operational/system role that ingests CAD and weather incidents, receives gateway delivery-report webhooks, drives the logical clock, and runs tick processing. `X-User-ID` for an `Integrator` is an opaque operator identifier not tied to any persisted entity.

The precise per-endpoint role assignments appear in the §4 endpoint table.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; the identifier is used only for addressing and referencing, never as a business-decision input. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version`. The `version` starts at 1 and increments by 1 on every mutation of that resource; whenever a resource is mutated, its `updated_at` is refreshed to the mutating instant. A derived-field recomputation (for example, refreshing a group's `member_count` or an alert's `pending_count`) counts as a mutation of the owning resource and therefore advances both `updated_at` and `version`.

### 2.5. The Logical Clock and Temporal Semantics

All time-dependent behavior is evaluated against a server-controlled logical clock, never against wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it continues to read that default. An integrator moves the clock by supplying a target instant as `to_iso8601`; the server adopts that value and echoes it back as `current_utc`. Delivery windows, retry back-off eligibility, throttle-window boundaries, gateway maintenance blackouts, and drill completion are all decided by comparing the relevant timestamps against this clock's current value.

Time-driven state changes do not happen spontaneously. Instead, an integrator invokes a tick-processing capability that, at the current clock value, flushes queued notifications on online gateways, drives the retry loop, completes due drills, auto-closes alerts whose in-flight count has reached zero, and advances dispatching alerts to fully sent. Each tick reports how many notifications were sent (`sent_count`), retried (`retried_count`), and exhausted (`exhausted_count`), along with `completed_drills` and `closed_alerts`.

### 2.6. Optimistic Concurrency on Dispatch

Dispatching an alert is guarded by optimistic concurrency control. The dispatch request must carry `expected_alert_version`, a non-optional field that must equal the target alert's current `version`. Between the moment a dispatcher last read the alert and the dispatch attempt, the alert's `version` may have advanced — for example, the alert may have been rejected back to editable draft and re-approved through the revision loop, or re-approved after a targeting edit. If `expected_alert_version` does not match the alert's current `version`, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a dispatcher cannot fan notifications out against a superseded targeting or approval snapshot. No other endpoint accepts or requires a version field.

### 2.7. Precision, Rounding, and Geospatial Matching

Reliability scores are reported to exactly two decimal places using round-half-up. Segment counts, reach counts, retry delays measured in seconds, and gateway window counts are all integers; target radii (`radius_m`, on subscriptions, alerts, and ingested incidents) are likewise supplied and stored as integers.

Geographic targeting uses a deterministic planar (equirectangular) distance with a fixed conversion of 111320 meters per degree and no latitude-cosine correction, so every match is reproducible and integer-valued. To test whether a subscription's centroid falls inside an alert's target circle, the system takes the difference in latitude between the subscription centroid and the alert centroid, multiplies it by 111320 meters per degree to obtain a north–south offset in meters, does the same with the longitude difference to obtain an east–west offset in meters, squares both offsets, sums them, takes the square root, and rounds that value half-up to whole meters. A subscription is matched when this rounded distance in meters is less than or equal to the alert's target radius in meters; the boundary is inclusive.

### 2.8. Nested Resource Retrieval and Path Validation

When an endpoint path names more than one resource — for example a channel nested under a contact, a localization nested under an alert, or a maintenance window nested under a gateway — the server validates each identifier left to right and rejects on the first that does not resolve, returning the not-found error specific to that resource type (`ERR_CONTACT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_GATEWAY_NOT_FOUND`, or `ERR_DRILL_NOT_FOUND`, all HTTP 404). Existence of the outer resource always takes precedence over any inner lookup or business rule.

### 2.9. Cascading Consistency and Derived Counters

Several operations mutate more than one resource in a single call, and the secondary effects are as much part of the contract as the primary transition. Two derived counters recur throughout the workflows and are always kept consistent with the notifications they summarize:

- An alert's `pending_count` is the number of that alert's notifications whose `delivery_status` is one of `QUEUED`, `SENT`, `RETRYING`, or `FAILED` — the messages still in flight. It is recomputed whenever a notification is created, delivered, exhausted, or suppressed, and whenever the alert is dispatched or cancelled.
- A gateway's `window_count` is the number of non-`SUPPRESSED` notifications whose `channel_type` equals the gateway's `channel_type` and whose `created_at` falls in the current throttle window. It is recomputed whenever a notification of that channel is created or suppressed.

Whenever a notification is suppressed — whether by an alert cancellation or by a channel opt-out — the owning alert's `pending_count` is decremented and every affected gateway's `window_count` is recomputed to drop the suppressed sends. When such a decrement drives an alert's `pending_count` to zero while the alert is dispatching or sent, the alert closes automatically and its final delivered reach is recorded, exactly as if a dispatcher had closed it explicitly.

### 2.10. Gateway Throttling Windows

Each channel is served by a gateway with a fixed `capacity_per_window` — the maximum number of notifications of that channel that may enter one throttle window. Throttle windows are aligned to the top of the UTC hour: the current window begins at the most recent hour boundary at or before the clock and ends 60 minutes later, and the interval is half-open — the start instant is included and the end instant is excluded. A gateway's `window_count` reflects only the non-`SUPPRESSED` notifications of its `channel_type` created inside that current window. Throttling is enforced at dispatch time as described in §3.5, and is bypassed entirely for the most severe alerts.

### 2.11. Validation Ordering and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order so the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_UNAUTHORIZED`), then existence of every resource named in the path (the resource-specific 404s of §2.8). After that comes state validity for the requested transition (`ERR_INVALID_STATE`, HTTP 409), then the dispatch optimistic-concurrency check (`ERR_STALE_VERSION`, HTTP 412). Next come referential preconditions on body references — a backing template must be published, a subscribed group must be open, and an opt-in token must match (`ERR_TEMPLATE_NOT_PUBLISHED`, `ERR_GROUP_NOT_OPEN`, `ERR_INVALID_TOKEN`). Following those are the cross-actor and uniqueness constraints — an approver or rejecter must differ from the author, a duplicate active subscription is forbidden, and an alert's effective window must be well-ordered (`ERR_SEGREGATION_OF_DUTIES`, `ERR_DUPLICATE_SUBSCRIPTION`, `ERR_INVALID_WINDOW`). Then the accessibility guarantee (`ERR_ACCESSIBILITY_UNMET`) is enforced, followed by temporal-window checks (`ERR_WINDOW_EXPIRED`, `ERR_WINDOW_OVERLAP`), then throttle capacity (`ERR_THROTTLE_EXCEEDED`), and finally the non-empty-recipient check (`ERR_NO_RECIPIENTS`). A malformed body, a missing required field, an invalid enum, or an out-of-range number is rejected with `ERR_VALIDATION` (HTTP 400).

For the dispatch endpoint specifically, this means the order of business checks is: state validity, then the stale-version check, then accessibility, then the effective-window check, then throttle capacity, and finally the recipient-set check.

## 3. Business Logic & Workflows

### 3.1. Building the Contact Database: Contacts and Channels

A `ContactAdmin` seeds the resident database by creating a contact with a `full_name`. Several preferences may accompany creation: a `primary_language` chosen from `EN`, `ES`, `ZH`, or `VI` (defaulting to `EN`); a `tty_required` flag marking a deaf or hard-of-hearing resident who must be reached on a TTY-capable channel (defaulting to false); a home location expressed as `default_lat` and `default_lon` in decimal degrees (each nullable, defaulting to null); and a quiet-hours window given as `quiet_start_min` and `quiet_end_min`, each an integer number of minutes from UTC midnight in the range 0 through 1439, or null for no quiet hours. A new contact's `status` begins as `ACTIVE` and may later read `SUSPENDED` or `DELETED`. Each contact also exposes a computed `reliability_score` described in §3.6.

A contact is reached through one or more channels. A `ContactAdmin` adds a channel to a contact by supplying its `channel_type` — one of `SMS`, `VOICE`, `EMAIL`, or `IPAWS` — an `address` holding the phone number or email address, and an optional `tty_capable` flag (defaulting to false) marking a channel that can carry TTY or relay traffic, such as a voice line with TTY or a TTY-capable SMS gateway. Each new channel records its owning `contact_id`, starts with `opt_in_status` of `PENDING`, and is minted a `confirmation_token`.

Consent belongs to the resident. Acting as a `Contact` on their own channel, a resident confirms opt-in by presenting a `confirmation_token`; the value must equal the channel's stored `confirmation_token` or the request is rejected with `ERR_INVALID_TOKEN`, and the acting resident's `X-User-ID` must equal the channel's `contact_id`. A successful confirmation advances the channel `PENDING → CONFIRMED`. A resident may also opt a channel out at any time, provided they own it; this advances the channel from either `PENDING` or `CONFIRMED` to the terminal `OPTED_OUT` and triggers the suppression cascade of §3.7. Channels can be listed for a contact and filtered by `opt_in_status`.

### 3.2. Targeting: Groups, Subscriptions, and Geo-Matching

Targeting rests on two mechanisms: named groups and geographic circles. A `ContactAdmin` creates a targeting group with a `name`; the group opens with `status` `OPEN` and exposes a computed `member_count` equal to the number of active group subscriptions that reference it. A `ContactAdmin` may close a group, advancing it `OPEN → CLOSED`; a closed group refuses new subscriptions.

A subscription links a resident to a target and may be created by a `ContactAdmin` or by the resident themselves acting as a `Contact`. The payload names the subscribing `contact_id`, a `subscription_type` of either `GROUP` or `GEO`, and — depending on type — either a `group_id` (required for `GROUP`, null for `GEO`) or a centroid given as `center_lat` and `center_lon` together with a `radius_m` (required for `GEO`; the radius is retained as metadata and is not itself used when matching an alert). A new subscription's `status` is `ACTIVE` and may later become `CANCELLED`. Creating a group subscription against a group that is not `OPEN` is rejected with `ERR_GROUP_NOT_OPEN`. The system also forbids duplication: if an `ACTIVE` subscription already exists for the same contact, type, and group or geo-centroid, the create is rejected with `ERR_DUPLICATE_SUBSCRIPTION`. Creating a group subscription recomputes the target group's `member_count`.

Subscriptions can be listed and filtered by `contact_id`, `group_id`, or `subscription_type`; a resident acting as a `Contact` sees only subscriptions whose `contact_id` equals their `X-User-ID`, regardless of the supplied filters. A subscription may be cancelled, advancing it `ACTIVE → CANCELLED`; a `ContactAdmin` may cancel any subscription, while a resident acting as a `Contact` may cancel only one whose `contact_id` equals their `X-User-ID`. Cancelling a group subscription recomputes the affected group's `member_count`.

Geographic matching, used both at dispatch and in the recipient preview, considers every `ACTIVE` `GEO` subscription. A contact is geo-matched when any of that contact's active geo subscriptions falls within the alert's target circle, measured by the planar distance rule of §2.7 with its inclusive boundary.

### 3.3. Templates and Alert Composition

Reusable message templates streamline composition. A `ContactAdmin` creates a template with a `name`, a `default_severity` chosen from `INFO`, `ADVISORY`, `WARNING`, or `CRITICAL`, and a `body_by_language` map from language code to message body (for example, an `EN` body and an `ES` body). A template opens in `DRAFT` and may be published by a `ContactAdmin`, advancing it `DRAFT → PUBLISHED`; a template's `status` may also read `ARCHIVED`. Only a published template may back a submitted alert.

A `Dispatcher` composes an alert, which opens in `DRAFT` with `version` 1, `revision_count` 0, and `author_user_id` set from the composing dispatcher's `X-User-ID`. Composition supplies a `title`, a `severity` from the same four-value set, and a `channels` array naming the requested delivery channel types as a subset of `SMS`, `VOICE`, `EMAIL`, and `IPAWS`. The alert's targeting is expressed with a `target_type` of `GROUP` or `GEO`: a group alert names a `target_group_id`, while a geo alert supplies `center_lat`, `center_lon`, and `radius_m` for its target circle. An optional `template_id` may reference a backing template. The alert's active interval is bounded by `effective_from` and `effective_until`, both ISO 8601 UTC instants. Composition may leave the computed reach and billing fields — `estimated_reach`, `delivered_reach`, `sms_billable_segments`, and `pending_count` — to be filled by later transitions, and `source_incident_ref` remains null unless the alert originated from an integration ingest.

Message text is carried per language. A `Dispatcher` adds a localization to an alert with a `language` (`EN`, `ES`, `ZH`, or `VI`) and its `message_text`, recorded under the owning `alert_id`. On creation the localization's `segment_count` is computed as the length of its `message_text` divided by 160 and rounded up to the next whole number. Localizations can be listed for an alert.

### 3.4. Approval Workflow and Segregation of Duties

Once an alert is ready, its `Dispatcher` submits it for approval, advancing it `DRAFT → PENDING_APPROVAL`. Submission enforces four preconditions. The alert must have at least one localization on record. Its targeting must be complete for its `target_type`: a group alert must have `target_group_id` set, and a geo alert must have all of `center_lat`, `center_lon`, and `radius_m` set; a targeting gap is rejected with `ERR_TARGET_REQUIRED`. If the alert names a backing `template_id`, that template's `status` must be `PUBLISHED`, or the submission is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`. Finally, `effective_from` must be strictly earlier than `effective_until`, or the submission is rejected with `ERR_INVALID_WINDOW`.

Approval is performed by a distinct reviewer. An `Approver` may approve a pending alert, advancing it `PENDING_APPROVAL → APPROVED`, but only if their `X-User-ID` differs from the alert's `author_user_id`; a reviewer attempting to approve their own alert is rejected with `ERR_SEGREGATION_OF_DUTIES`. An `Approver` may instead reject a pending alert, advancing it `PENDING_APPROVAL → DRAFT` and incrementing the alert's `revision_count` by 1 so the dispatcher can revise and resubmit; an optional `reason` may accompany the rejection. The same segregation check applies to rejection: the rejecting reviewer's `X-User-ID` must differ from `author_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. This revision loop — pending back to draft and forward again — is exactly why a later dispatch is version-guarded.

### 3.5. Dispatch: Recipient Resolution, Reach, and Billing

Before committing, a `Dispatcher` or `Approver` may request a non-mutating recipient preview, which resolves the current targeting and returns the projected `estimated_reach`, the `matched_contact_ids`, and the `throttled_contact_ids` without changing any state. Here `matched_contact_ids` is the resolvable recipient set — the matched, `ACTIVE` contacts that have at least one `CONFIRMED` channel of a requested `channel_type` — returned as a list of ids sorted in ascending order; `throttled_contact_ids` is the subset of those recipients whose every eligible channel is served by a gateway that would exceed its `capacity_per_window` (always empty when `severity` is `CRITICAL`, since throttling is then bypassed), likewise sorted in ascending order; and the projected `estimated_reach` is the count of `matched_contact_ids` that are not throttled.

Dispatch itself is performed by a `Dispatcher` on an approved alert and advances it `APPROVED → DISPATCHING`. The request carries `expected_alert_version` for the optimistic-concurrency guard of §2.6. Several preconditions gate the transition. Every targeted contact who is `tty_required` — that is, every matched, `ACTIVE` contact — must have at least one `CONFIRMED`, `tty_capable` channel whose `channel_type` is among the alert's requested `channels`; if any such contact lacks one, dispatch is rejected with `ERR_ACCESSIBILITY_UNMET`. The current clock must fall in the half-open interval from `effective_from` up to but not including `effective_until`; a dispatch at or after `effective_until`, or before `effective_from`, is rejected with `ERR_WINDOW_EXPIRED`. For each requested `channel_type`, the serving gateway's projected `window_count` plus the number of new sends of that channel must not exceed the gateway's `capacity_per_window` — unless the alert's `severity` is `CRITICAL`, in which case the throttle is bypassed entirely; a non-critical alert that would exceed capacity is rejected with `ERR_THROTTLE_EXCEEDED`. Finally, the resolved recipient set must be non-empty, or dispatch is rejected with `ERR_NO_RECIPIENTS`.

The resolved recipient set consists of the matched, `ACTIVE` contacts that have at least one `CONFIRMED` channel of a requested `channel_type` and are not throttle-skipped. On a successful dispatch the alert's `version` increments by 1, and the system creates one notification for every pairing of a matched contact with one of that contact's `CONFIRMED` channels whose `channel_type` is among the requested `channels`. Each notification records its source `alert_id`, recipient `contact_id`, the recipient `channel_id`, the `channel_type` copied from that channel, and the `language` selected for the recipient — the contact's `primary_language` when a matching localization exists on the alert, otherwise falling back to `EN`. Each notification opens with `delivery_status` `QUEUED`, `receipt_status` `NONE`, `attempt_count` 0, and a null `next_retry_at`.

Dispatch then sets two computed figures. The alert's `estimated_reach` is set to the number of distinct contacts that received at least one created notification — a forward-looking snapshot that treats every queued send as a reach. The alert's `sms_billable_segments` is computed with a pinned rounding order: for each SMS notification, take the localization matching that notification's `alert_id` and `language`, compute that localization's segment count as the length of its `message_text` divided by 160 rounded up to a whole number, and then sum those per-notification segment counts across all of the alert's SMS notifications. The rounding is performed per notification before summing, never by summing raw character counts and dividing once. Dispatch also recomputes the alert's `pending_count` and each affected gateway's `window_count`.

### 3.6. Delivery, Receipts, and the Retry Loop

Queued notifications do not move on their own; they advance when an integrator runs tick processing. At a tick, a `QUEUED` notification advances `QUEUED → SENT` only if its parent alert is still `DISPATCHING`, its recipient contact is `ACTIVE`, and the online gateway for its `channel_type` exists and is `ONLINE`; on that transition its `attempt_count` becomes 1. If the serving gateway is `OFFLINE`, the notification stays `QUEUED`. Once no queued notifications remain for a dispatching alert, the alert advances `DISPATCHING → SENT`.

Delivery outcomes arrive through the gateway webhook. An `Integrator` posts a delivery report with an `outcome` of `DELIVERED` or `FAILED`. A `DELIVERED` outcome advances the notification `SENT → DELIVERED`, decrements the parent alert's `pending_count`, and — if that decrement brings `pending_count` to zero while the alert is `SENT` — closes the alert and records its delivered reach. A `FAILED` outcome advances the notification `SENT → FAILED`.

Failed notifications enter a retry loop driven by ticks. There is a base retry delay of 60 seconds, a maximum back-off of 3600 seconds (one hour), and a maximum of 3 attempts. When a tick processes a `FAILED` notification whose `attempt_count` is still below 3, the notification advances `FAILED → RETRYING` and its `next_retry_at` is set to the current clock plus a back-off delay. The back-off delay is computed from the base delay of 60 seconds multiplied by two raised to the power of one less than the current `attempt_count`, multiplied by a severity factor of 1 for `INFO`, 1 for `ADVISORY`, 2 for `WARNING`, and 4 for `CRITICAL`; the result is then capped at 3600 seconds by taking the smaller of the capped maximum and the computed value. When a later tick finds a `RETRYING` notification whose `next_retry_at` is at or before the current clock, the notification advances `RETRYING → SENT`, its `attempt_count` increments by 1, and `next_retry_at` returns to null. When a tick processes a `FAILED` notification whose `attempt_count` has reached 3 or more, the notification advances `FAILED → EXHAUSTED` and the parent alert's `pending_count` is decremented.

Receipts evolve on a dimension parallel to delivery. A notification's `receipt_status` begins `NONE` and can advance to `ACKNOWLEDGED` when the recipient, acting as a `Contact` whose `X-User-ID` equals the notification's `contact_id`, acknowledges it — permitted only while the notification's `delivery_status` is `SENT`, `DELIVERED`, or `RETRYING`. If the notification was `SENT` at the moment of acknowledgement, that same acknowledgement also advances its `delivery_status` `SENT → DELIVERED` (carrying the pending-count decrement and possible auto-close with it).

A contact's `reliability_score` is computed on the fly from its notification history. Let the denominator be the count of that contact's notifications whose `delivery_status` is one of `SENT`, `DELIVERED`, `FAILED`, `EXHAUSTED`, or `RETRYING`. If that denominator is zero, the score is 0.00. Otherwise the score is the number of successful notifications divided by that denominator, rounded half-up to two decimal places. Two definitions of "successful" exist: the default optimistic read counts notifications whose `delivery_status` is `SENT`, `DELIVERED`, or `RETRYING` as successes, while the strict read — selected by the `mode` query parameter set to strict — counts only `DELIVERED` notifications as successes. The two diverge whenever a sent or retrying notification has not yet been delivered.

### 3.7. Suppression Cascades and Alert Closure

Two events suppress in-flight notifications, and both cascade. When a resident opts a channel out (`PENDING`/`CONFIRMED` → `OPTED_OUT`), every non-terminal notification on that channel — those with `delivery_status` in `QUEUED`, `SENT`, `RETRYING`, or `FAILED` — advances to the terminal `SUPPRESSED`; each such suppression decrements its parent alert's `pending_count`; when an affected alert's `pending_count` reaches zero while that alert is `DISPATCHING` or `SENT`, that alert advances to `CLOSED` and its `delivered_reach` is recorded; and every affected gateway's `window_count` is recomputed to drop the suppressed sends.

A `Dispatcher` may cancel an alert from any of `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `DISPATCHING`, or `SENT`, advancing it to the terminal `CANCELLED`. Cancellation suppresses every non-terminal notification of the alert (`QUEUED`, `SENT`, `RETRYING`, `FAILED` → `SUPPRESSED`), which in turn triggers a recompute of each affected gateway's `window_count` to drop those suppressed sends, and the alert's `pending_count` is recomputed to zero.

An alert reaches its natural terminal state when its work is done. A `Dispatcher` may close a `SENT` alert explicitly (`SENT → CLOSED`), and the system closes a `SENT` alert automatically once its `pending_count` has reached zero. On either path to `CLOSED`, the alert's `delivered_reach` is set to the number of distinct contacts having at least one `DELIVERED` notification — the final tally, which excludes failed, exhausted, suppressed, and still-pending sends and therefore may be smaller than the forward-looking `estimated_reach` recorded at dispatch.

### 3.8. Gateways, Maintenance, Drills, and Integration Ingest

A `ContactAdmin` registers a gateway with a `name`, the `channel_type` it carries, and its `capacity_per_window` (a non-negative integer); a new gateway opens `ONLINE` and exposes the computed `window_count` of §2.10. A `ContactAdmin` may toggle a gateway between `ONLINE` and `OFFLINE` by supplying the desired `status`. An offline gateway holds its notifications in `QUEUED` at tick time, as described in §3.6.

A `ContactAdmin` may schedule maintenance on a gateway by supplying a `start_at` and `end_at`, recorded under the owning `gateway_id`. A maintenance window is half-open: it includes its `start_at` and excludes its `end_at`, so a new window whose `start_at` equals an existing window's `end_at` is adjacent and allowed, but any true overlap with an existing window on that gateway is rejected with `ERR_WINDOW_OVERLAP`. Maintenance windows can be listed for a gateway.

A `ContactAdmin` schedules a drill against a group by supplying the `group_id`, a `scheduled_start`, and a `scheduled_end`; the drill opens `SCHEDULED`. Drill scheduling is closed on both ends (both the start and end instants are part of the exercise) and enforces a 30-minute buffer gap: a new drill on the same group that falls within 30 minutes of an existing `SCHEDULED` drill on that group is rejected with `ERR_WINDOW_OVERLAP`. A `ContactAdmin` may cancel a scheduled drill (`SCHEDULED → CANCELLED`), and tick processing completes a scheduled drill (`SCHEDULED → COMPLETED`) once its `scheduled_end` is at or before the current clock. Drills can be listed and filtered by `group_id` and `status`.

Alerts may also be born from external feeds. An `Integrator` ingests a CAD or weather incident by supplying its `source`, an `external_ref`, a mapped `severity`, the incident circle as `center_lat`, `center_lon`, and `radius_m`, and the requested `channels`. An optional `title` may accompany the ingest, defaulting to the `external_ref` when omitted, and optional `effective_from` and `effective_until` instants may be supplied, each defaulting to null. Ingest creates a `DRAFT` alert with `target_type` `GEO`, its `source_incident_ref` set to the supplied `external_ref`, and `author_user_id` set from the integrator's `X-User-ID`; from there the alert follows the same localization, submission, approval, and dispatch path as any dispatcher-composed alert.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act on an existing resource return `200 OK`. State-driving actions and computed reads on existing resources return `200 OK` even though they change state.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Integrator |
| POST | `/_tick/run` | Advance system processing at the current clock | Integrator |
| POST | `/_integration/ingest_incident` | Ingest a CAD/weather incident as a DRAFT alert | Integrator |
| POST | `/contacts` | Create a contact | ContactAdmin |
| GET | `/contacts/{id}` | Get a contact (optional `mode=strict` reliability) | ContactAdmin, Dispatcher, Approver, Contact |
| POST | `/contacts/{id}/channels` | Add a channel to a contact | ContactAdmin |
| GET | `/contacts/{id}/channels` | List a contact's channels | ContactAdmin, Dispatcher, Contact |
| POST | `/channels/{id}/confirm` | Confirm a channel opt-in with the token | Contact |
| POST | `/channels/{id}/opt-out` | Opt a channel out (cascades suppression) | Contact |
| POST | `/groups` | Create a targeting group | ContactAdmin |
| GET | `/groups/{id}` | Get a group | ContactAdmin, Dispatcher, Approver |
| POST | `/groups/{id}/close` | Close a group | ContactAdmin |
| POST | `/subscriptions` | Create a subscription (GROUP or GEO) | ContactAdmin, Contact |
| GET | `/subscriptions/{id}` | Get a subscription | ContactAdmin, Dispatcher, Contact |
| GET | `/subscriptions` | List subscriptions by contact/group/type | ContactAdmin, Dispatcher, Contact |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | ContactAdmin, Contact |
| POST | `/templates` | Create a template (DRAFT) | ContactAdmin |
| GET | `/templates/{id}` | Get a template | ContactAdmin, Dispatcher |
| POST | `/templates/{id}/publish` | Publish a template | ContactAdmin |
| POST | `/alerts` | Compose an alert (DRAFT) | Dispatcher |
| GET | `/alerts/{id}` | Get an alert | ContactAdmin, Dispatcher, Approver, Integrator |
| GET | `/alerts` | List alerts by status/template/target group | ContactAdmin, Dispatcher, Approver |
| POST | `/alerts/{id}/localizations` | Add a language localization | Dispatcher |
| GET | `/alerts/{id}/localizations` | List an alert's localizations | ContactAdmin, Dispatcher, Approver |
| POST | `/alerts/{id}/submit` | Submit an alert for approval | Dispatcher |
| POST | `/alerts/{id}/approve` | Approve an alert | Approver |
| POST | `/alerts/{id}/reject` | Reject an alert back to DRAFT | Approver |
| POST | `/alerts/{id}/preview` | Non-mutating recipient/reach preview | Dispatcher, Approver |
| POST | `/alerts/{id}/dispatch` | Dispatch an APPROVED alert (OCC) | Dispatcher |
| POST | `/alerts/{id}/cancel` | Cancel an alert (cascades suppression) | Dispatcher |
| POST | `/alerts/{id}/close` | Close a SENT alert; finalize delivered_reach | Dispatcher |
| GET | `/notifications/{id}` | Get a notification | ContactAdmin, Dispatcher, Integrator, Contact |
| GET | `/notifications` | List notifications by alert/contact/channel/delivery-status; a Contact sees only their own | ContactAdmin, Dispatcher, Integrator, Contact |
| POST | `/notifications/{id}/delivery-report` | Gateway delivery-receipt webhook | Integrator |
| POST | `/notifications/{id}/acknowledge` | Recipient acknowledges receipt | Contact |
| POST | `/gateways` | Register a channel gateway (ONLINE) | ContactAdmin |
| GET | `/gateways/{id}` | Get a gateway (with computed window_count) | ContactAdmin, Dispatcher, Integrator |
| POST | `/gateways/{id}/toggle` | Toggle a gateway ONLINE/OFFLINE | ContactAdmin |
| POST | `/gateways/{id}/maintenance-windows` | Schedule a maintenance window | ContactAdmin |
| GET | `/gateways/{id}/maintenance-windows` | List a gateway's maintenance windows | ContactAdmin, Dispatcher, Integrator |
| POST | `/drills` | Schedule a drill for a group | ContactAdmin |
| GET | `/drills/{id}` | Get a drill | ContactAdmin, Dispatcher |
| GET | `/drills` | List drills by group/status | ContactAdmin, Dispatcher |
| POST | `/drills/{id}/cancel` | Cancel a scheduled drill | ContactAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_CONTACT_NOT_FOUND` | 404 |
| `ERR_CHANNEL_NOT_FOUND` | 404 |
| `ERR_GROUP_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_TEMPLATE_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_GATEWAY_NOT_FOUND` | 404 |
| `ERR_DRILL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_TEMPLATE_NOT_PUBLISHED` | 422 |
| `ERR_GROUP_NOT_OPEN` | 409 |
| `ERR_INVALID_TOKEN` | 422 |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 |
| `ERR_INVALID_WINDOW` | 409 |
| `ERR_ACCESSIBILITY_UNMET` | 422 |
| `ERR_WINDOW_EXPIRED` | 422 |
| `ERR_WINDOW_OVERLAP` | 422 |
| `ERR_THROTTLE_EXCEEDED` | 409 |
| `ERR_NO_RECIPIENTS` | 422 |
| `ERR_TARGET_REQUIRED` | 422 |
