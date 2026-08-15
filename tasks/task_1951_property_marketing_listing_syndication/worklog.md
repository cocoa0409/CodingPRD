# Worklog — task_1951_property_marketing_listing_syndication

## Step 2: Generate Scaffold — 2026-08-15T03:17:00.000Z

All three artifacts are complete and pass lint. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1951_property_marketing_listing_syndication/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (fixed response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC); no difficulty/corner keys inside.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`.

**Counts:**
- Entities: **12** (Agent, Listing, MediaAsset, ComplianceReview, PortalAccount, BlackoutWindow, FeedSubscription, SyndicationJob, ListingEvent, ShowingWindow, ShowingFeedback, RelistRequest)
- State machines: **8** (Listing lifecycle with a derived parallel posture dimension; cyclic SyndicationJob retry machine; cyclic FeedSubscription; ComplianceReview; MediaAsset; ShowingWindow; ShowingFeedback)
- Endpoints: **52** (per lint), including `/_clock/set_current_utc` (default 2026-08-01T00:00:00Z) and `/_sweeps/run`
- Errors: 29; Validations: 25 priority-ordered; Concurrency rules: 2 OCC (PATCH listing, price-changes)
- Difficulty instances: **18** (2 per each of the 9 rules)
- Corner instances: **48** entries (44 active with full recipes + 4 `excluded_because` stubs)

**Difficulty design highlights (max-depth as requested):** dual-variant calcs on two different entity domains (decay-weighted showing-feedback scores vs provisional/audited SLA breach counts); combinatorial formulas in two different modes (3-input tiered relist fee vs order-pinned nested portal price rounding); a depth-4 withdraw cascade (Listing → FeedSubscription → SyndicationJob → derived posture) and a depth-3 price-change cascade; two priority conflicts on different category pairs (state vs business_constraint; business_safety vs business_temporal); boundary precision on two different metrics/endpoints (cents delta ≥ vs strict-> SLA seconds); cross-entity gates on two different pairs (Listing←ComplianceReview, FeedSubscription←PortalAccount); two temporal-overlap semantics (half-open showing windows vs closed + 15-minute-buffered portal blackouts); two compensating invariants on different conserved quantities (price-vs-history-head equality, exactly-one-primary-photo count).

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (513 calls scanned). All numeric assertions were pre-computed (e.g., relist fee 15000/30000/20000, weighted score 3.667 vs raw 4.0, display prices 48000000/50000000/49000000). No forbidden concurrency vocabulary; all 66 instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-08-15T03:18:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1951_property_marketing_listing_syndication/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T03:30:00.000Z

All audits pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1951_property_marketing_listing_syndication/workspace/PRD.md` — 347 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC (5 roles + identity binding), 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock & Operations Sweep, 2.5 Common Resource Properties & Mutation Semantics (incl. the `common_fields: false` exception for BlackoutWindow/ListingEvent), 2.6 Derived Read-Time State (5-rule posture precedence), 2.7 Money/Precision/Rounding, 2.8 OCC, 2.9 Validation Order & Nested Resolution, 2.10 Fair-Housing Language Policy
- §3 Business Logic — 3.1 Agents & Listing Intake, 3.2 Media Assets & Primary Photo Curation, 3.3 Compliance Review & the Compliance Hold, 3.4 Activation/Contract/Leaving the Market, 3.5 Portal Accounts/Blackouts/Subscriptions (portal display price formula), 3.6 Syndication Jobs (dispatch/backoff/breach counters), 3.7 Price Changes & Event History, 3.8 Showing Windows & Feedback Aggregation, 3.9 Relisting (cooldown, quote, tiered fee)
- §4 Endpoint Definitions (52 endpoints, 4-column table), §5 Error Code Catalogue (29 errors, 2-column table)

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input (incl. query params): 77 required, 77 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed (global order §2.9 + per-endpoint order in §3.2/3.3/3.5/3.7/3.8/3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (listing update + price change, expected_listing_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 31 checked across 8 machines, 31 fully expressed, 0 missing
- calculations[]: 4 checked (feedback scores, breach audit, relist fee, portal display price), 4 fully expressed in reconstructible prose, 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (cascades, supersede, posture-guard scope of 7 operations, fair-housing 4 trigger moments), 0 missing
- entities[].fields[] structured content: defaults/ranges/nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (posture rules, ack/fail, approve/reject, archive branches, job-event payload triplets, withdraw/expire), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 424
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: all 49 enum/state values appear verbatim (initial audit caught `FAILED` and `CANCELLED` missing as exact tokens; fixed by naming the `FAILED` intermediate state and using `CANCELLED` tokens in the four cascade passages); all 29 error IDs appear in §2/§3 prose; §2.2 block verified byte-identical. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T04:05:00.000Z

Generation complete and all self-checks pass.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1951_property_marketing_listing_syndication/`):

`test_helpers/` (Stage 1): `types.py` (14 TypedDicts + 12 enums; `BlackoutWindow`/`ListingEvent` correctly omit `updated_at`/`version` per PRD §2.5 append-only rule), `api_client.py` (44 endpoint methods, one per PRD §4 route), `api_errors.py` (all 29 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions), `factories.py` (input-field-only payload factories; optional fields omitted when unset), `constants.py` (PRD §3 thresholds), `test_users.py` (opaque-role shared constants + mandatory `make_listing_agent_headers` per-instance builder for the entity-backed ListingAgent role), `fixtures.py` (composite setup tiers: intake→READY-photo→submit→approve→activate, syndicated listing, withdrawn listing, job finders, clock/sweep, window/feedback helpers), `__init__.py` barrel.

`test_suite/` (Stage 2): `conftest.py` + 10 test files (`test_01_agents_and_listing_intake` … `test_10_rbac_patch_and_envelope`).

**Test count: 79**, all collected cleanly by pytest (`--collect-only` passes).

**Queue A (difficulty):** 18/18 instances translated, exactly 2 tests each = 36 tests.

**Queue B (corner):** 43/44 non-stub instances translated = 43 tests. 4 `excluded_because:` stubs not translated (all cross-references verified to resolve). **1 instance skipped:** `Corner/validations/subscribe_draft_listing_returns_listing_not_active` — PRD §3.5 states portal-ACTIVE and duplicate checks for subscription creation but never states that subscription creation requires the listing to be `ACTIVE` (the `ERR_LISTING_NOT_ACTIVE` requirement appears only for *resume*). Two PRD-only readers could legitimately differ, so the asserted outcome is not uniquely derivable; the gap is left as a gap.

**Two design-index repairs applied (PRD wins over the index):**
1. `portal_display_price_nested_rounding`: the instance's portal A used `rounding_increment_cents: 500000`, which PRD §3.5 forbids (allowed: 10000/50000/100000/1000000) — setup would 400 under any conformant implementation. Repaired to 1000000, which preserves every asserted value exactly (48000000 / 50000000 / headline 48000000; the forbidden-order contrast 48150000 also survives). Documented inline.
2. `withdraw_cascade_...`: the instance asserted `terminal_price_cents == 50000000` after a pre-withdrawal price change to 49900000; PRD §3.4 freezes `terminal_price_cents` at the *then-current* price, so the test asserts 49900000.

**Validation results:**
- Tag audit: 79/79 tests carry exactly one `Design:` tag; every tag resolves to a real instance; no stub tags used.
- Coverage audit: 0 difficulty instances below 2 tests; only the deliberately-skipped corner instance below 1.
- PRD verbatim pass: 130 quoted citation blocks extracted from docstrings, all found verbatim in `PRD.md` (modulo whitespace).
- No `skip`/`skipif`/`xfail` markers; no "scaffold"/table references in generated code comments.

## Step 6: Generate Implementation — 2026-08-15T04:05:00.000Z

Implementation complete. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1951_property_marketing_listing_syndication/workspace/implementation/`:

- `start.sh` — evaluator contract: `cd`s to its own dir, guards dependency install behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground on `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` (flask), `app.py` (entry point, blueprint registration, ApiError/404/405/HTTPException handlers all emitting the spec error envelope)
- `clock.py` — logical clock (boots at exactly `2026-08-01T00:00:00Z`, never wall-clock) + ISO-8601 parse/format (3 fractional digits)
- `db.py` — in-memory store, starts empty, zero seeding
- `errors.py` (full 29-error catalog), `response.py` (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta)
- `middleware.py` — X-User-ID/X-User-Role auth, 5-role RBAC, ListingAgent ownership, typed field validators, limit/offset pagination (default 10, 1–100)
- `services/derived.py` — read-time posture (SUSPENDED override → sticky DEGRADED → SYNDICATING → SYNDICATED → NOT_SYNDICATED), audited/provisional breach counts (strict `>` SLA), raw + 14-day-half-life decayed feedback scores (3dp ROUND_HALF_UP), portal display price (discount on exact unrounded price, single half-up round at the increment division), relist fee (tier → volume → discount, one final rounding)
- `services/ops.py` — fair-housing scan (exact 6-phrase case-insensitive list), event log (per-listing `seq` from 1), job queueing with same-type QUEUED supersede, live-job cancel, terminal/hold cascades (parent version +1 exactly once; each cascaded child gets its own version bump + timestamp)
- `services/serialize.py`, and `routes/`: `agents.py`, `listings.py`, `media.py`, `compliance.py`, `portals.py`, `subscriptions.py`, `feed_events.py`, `showings.py`, `admin.py`

## Endpoints: 52/52 implemented (every row of the endpoint table, including `/_clock/set_current_utc` and `/_sweeps/run`)

## State machines: 8 — Listing lifecycle (DRAFT→…→SOLD, expiry sweep, relist to DRAFT), derived ListingPosture (rule-ordered, sticky DEGRADED), SyndicationJob (QUEUED/DISPATCHED/ACKED/RETRY_QUEUED with `60 * 2^attempt_count` backoff per the scaffold formula, DEAD_LETTER at attempt 3, SUPERSEDED/CANCELLED), FeedSubscription (SUBSCRIBED/PAUSED/COMPLETED via TERMINAL_SYNC ack), ComplianceReview (with rejection cascade to COMPLIANCE_HOLD), MediaAsset (auto-primary, atomic set-primary swap, archive reassignment by earliest created_at), ShowingWindow, ShowingFeedback.

## Boot verification

Ran `bash start.sh` exactly as the evaluator does (fresh process, custom PORT): server came up within ~2s; `/agents` returns 401 `ERR_UNAUTHENTICATED` in the spec envelope; authenticated list shows empty store, pagination meta, and clock stamped `2026-08-01T00:00:00.000Z`. Two smoke suites (≈95 assertions, both fully passing) covered: full lifecycle (intake → media → review → activate → subscribe → dispatch → ack/fail/retry/DEAD_LETTER → DEGRADED → under-contract → SOLD cascade → TERMINAL_SYNC → COMPLETED), compliance rejection cascade + revise, OCC 412s, ownership 403s, fair-housing 422 precedence, withdraw/expire + relist (cooldown boundary at exactly 30 days, quote, fee 15000 with 6% reduction → 0.25 discount), blackout 15-minute buffered deferral, portal suspend/resume blocking, job supersede, SLA-boundary breach semantics (delay == SLA is not a breach; in-flight overage counts provisional-only), weighted feedback aging (verified 2.330 against a hand-computed Decimal oracle), exclusion recompute, primary swap/reassignment, and pagination validation.

One judgment call to flag: the PRD's retry-backoff prose formula (`60 * 2^attempt_count` seconds, matching the scaffold in two places) conflicts with its own parenthetical example ("one minute after the first failure"). I implemented the formula (120s after first failure), siding with the scaffold since it is the source of truth for test generation.

## Step 7: Run Tests and Iterate — 2026-08-15T04:20:00.000Z

All 8 rounds pass 79/79. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep surfaced failures; verification sweep after fixes passed 8/8 rounds, 79/79 tests each).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `test_04_lifecycle_cascades.py::test_reactivate_under_contract_cycle_with_status_jobs` — removed the generated `all(j["status"] == "QUEUED")` assertion, which contradicted PRD §3.6's verbatim supersede rule ("Creating a newer job of the same `job_type` for the same subscription supersedes any still-`QUEUED` job of that type, moving it to `SUPERSEDED`"). The test now asserts the PRD-faithful outcome: exactly 2 STATUS_UPDATE jobs (one per transition per §3.4), the older `SUPERSEDED` with `completed_at` stamped, the newer `QUEUED`. Added the §3.6 citation to the docstring.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `routes/listings.py::submit_review` — the state gate required lifecycle `DRAFT` only, so a second submit while a review was `PENDING` (listing in `PENDING_REVIEW`) tripped `ERR_INVALID_STATE` at gate 6 before reaching §3.3's fourth business check. Since a `PENDING` review can only ever coexist with a `PENDING_REVIEW` listing, the DRAFT-only gate rendered PRD §3.3's explicit check ("Fourth, there must be no other compliance review still `PENDING` for this listing, else `ERR_REVIEW_ALREADY_PENDING`") permanently unreachable — the PRD's own text forces the gate to admit `PENDING_REVIEW`. Changed the gate to `in ("DRAFT", "PENDING_REVIEW")`; `ACTIVE` and other states still get `ERR_INVALID_STATE` (verified by the still-passing `test_submit_review_from_active_rejected_invalid_state`). Also made the `STATUS_CHANGE` event's `from_lifecycle` dynamic instead of hardcoded `"DRAFT"` so the audit trail stays truthful on the re-submit edge.

**Diagnostic detail:** Both failures were deterministic (8/8 rounds) — no flakiness. Failure 1: expected `ERR_REVIEW_ALREADY_PENDING`, got `ERR_INVALID_STATE` (implementation bug, PRD §3.3 check 4 unreachable). Failure 2: `all(... == QUEUED)` was `False` because the implementation correctly superseded the first STATUS_UPDATE job per §3.6 (test bug; the corner design recipe asserted only "exactly 2 STATUS_UPDATE jobs exist", never both-QUEUED).

## Step 8: Finalize PRD — 2026-08-15T04:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1951_property_marketing_listing_syndication/workspace/PRD_FINALIZED.md` is written.

## Summary

**Line counts / delta:** PRD.md 347 lines, PRD_FINALIZED.md 347 lines (single inline paragraph replacement); character delta +1.40%.

**Step 7 diff item triage:**
- *Test fix* (`test_04_lifecycle_cascades.py::test_reactivate_under_contract_cycle_with_status_jobs`) — pure test bug, **no PRD edit**. The deleted `all(j["status"] == "QUEUED")` assertion contradicted PRD §3.6's already-verbatim supersede rule ("Creating a newer job of the same `job_type` for the same subscription supersedes any still-`QUEUED` job of that type, moving it to `SUPERSEDED` and stamping its `completed_at`") combined with §3.4's one-`STATUS_UPDATE`-per-transition rule. Implementation (`services/ops.py:65-91` `queue_job`) matches the PRD exactly, superseding only `QUEUED` jobs.
- *Implementation fix* (`routes/listings.py::submit_review`) — **one PRD edit** (below).

**Change list:**
- §3.3 — revise — widened the submit-review state gate from the implied DRAFT-only to explicitly admitting `DRAFT` or `PENDING_REVIEW` (any other lifecycle → `ERR_INVALID_STATE` at §2.9 step 6, ahead of the four business checks), and changed the `STATUS_CHANGE` event wording from the hardcoded "move from `DRAFT` to `PENDING_REVIEW`" to a dynamic `from_lifecycle` recorded at submission, with the `PENDING_REVIEW` → `PENDING_REVIEW` self-loop pinned for the approved-but-not-yet-activated re-submit edge — `implementation/routes/listings.py:195-237` (gate at :203, dynamic event at :232-234).

**Per-edit pre-edit search log:**
1. (a) **Subject:** submit-review admission states and the payload of its `STATUS_CHANGE` event.
   (b) **Paths enumerated and read/grepped:** `routes/listings.py:195-237` (`submit_review` — gate, four checks in order, dynamic `from_lifecycle`, `touch`); `routes/compliance.py:33-60` (`decide` — approve leaves the listing in `PENDING_REVIEW`, which is the only way the re-submit success edge arises; reject cascades via `lifecycle_transition`); `routes/listings.py:240-261` (`activate` — requires `PENDING_REVIEW`); `routes/listings.py:264-276` (`revise`); repo-wide grep for `PENDING_REVIEW` (all hits listed above); grep for all `STATUS_CHANGE`/`from_lifecycle` sites (`ops.py:133`, `listings.py:232,258,273,288,304,382` — every site already records the truthful from-state); `services/derived.py:55` (posture override list excludes `PENDING_REVIEW`, so no posture claim needed); `test_suite/test_02_compliance_workflow.py` (still-passing `test_submit_review_from_active_rejected_invalid_state` confirms `ACTIVE` → `ERR_INVALID_STATE`; `test_submit_twice_returns_review_already_pending` confirms the newly reachable fourth check).
   (c) **Wording adjustment:** initial draft said "moves it to `PENDING_REVIEW`" only; revised to also (i) anchor the gate at §2.9 step 6 so the four-check ordering text stays intact, (ii) avoid any universal claim that submission always implies a lifecycle change (the self-loop event wording covers both the `DRAFT` and the approved-but-inactive re-submit paths), and (iii) explicitly exclude other lifecycles so the still-passing `ACTIVE`-rejection behavior remains pinned.

## Step 9: Complete PRD — 2026-08-15T04:45:00.000Z

All 20 edits landed as in-paragraph inserts/revisions across 15 lines; line count unchanged (347 → 347), no sections added. Final summary:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (347 lines / 49,930 chars) → `PRD_COMPLETED.md` (347 lines / 52,200 chars). Char delta: **+2,270**. All changes are inline sentence inserts/revisions within existing paragraphs; no new sections, no restructuring.

**Counts:** 20 edits total — **16 ambiguity-pins**, **4 mismatch-revisions** (two edits are mixed: the §3.1 intake edit contains both a pin and a revision; the §3.9 effects edit likewise).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` rejected with `ERR_INVALID_REQUEST` — implementation/middleware.py:126-147
- §2.3 — insert — ambiguity — list ordering ties on `created_at` broken by creation sequence (global insertion counter `_seq`), earliest first — implementation/routes/listings.py:125-126, implementation/db.py:21
- §2.4 — insert — ambiguity — clock set capability accepts any target instant, earlier or later; no monotonicity check — implementation/routes/admin.py:16-23
- §2.4 — insert — ambiguity — sweep processes expiries before dispatch within a run (so a `TERMINAL_SYNC` queued by an expiry is dispatch-eligible in that run); `expired_listing_ids` in listing creation order, dispatched/deferred ids in batch order — implementation/routes/admin.py:42-79
- §3.1 — revise — **mismatch** (mixed edit) — dropped "two-letter" qualifier on `state_code` (impl enforces only string type, no length) — implementation/routes/listings.py:83
- §3.1 — insert — ambiguity (same edit) — `agent_id` pinned as a required intake field that must resolve to a registered agent (`ERR_INVALID_REQUEST` if absent, `ERR_NOT_FOUND` if unresolvable) — implementation/routes/listings.py:71-80
- §3.1 — insert — ambiguity — `bedrooms`/`square_feet` must be integers; `bathrooms` may be any number including fractional — implementation/routes/listings.py:88-90, implementation/middleware.py:70-89
- §3.2 — insert — ambiguity — primary-photo reassignment on archive breaks earliest-`created_at` ties by creation order — implementation/routes/media.py:187-194
- §3.2 — revise — **mismatch** — media jobs on archive are queued only when the archived asset was `READY`; archiving a `REJECTED` asset queues no jobs (PRD previously said jobs queue on archive unconditionally) — implementation/routes/media.py:195-196
- §3.4 — insert — ambiguity — terminal cascade pauses only `SUBSCRIBED` subscriptions; a subscription already `PAUSED` before the transition is left untouched and receives no `TERMINAL_SYNC` — implementation/services/ops.py:136-141
- §3.5 — insert — ambiguity — portal accounts are listable with an optional `status` filter — implementation/routes/portals.py:53-63
- §3.6 — insert — ambiguity — event-queued jobs are born due (`scheduled_at` = creation instant), and every job of every type snapshots the subscription's portal display price into `payload_display_price_cents` at creation — implementation/services/ops.py:75-91
- §3.6 — insert — ambiguity — dispatch batch order extended: remaining ties after `scheduled_at`/`created_at` broken by creation order — implementation/routes/admin.py:53-57
- §3.6 — revise — ambiguity — `propagation_delay_seconds` is the whole number of seconds, fractional part truncated (was "exact number of seconds") — implementation/routes/feed_events.py:59-60
- §3.6 — insert — ambiguity — "listing that has left the market" for `TERMINAL_SYNC` ack completion pinned to current `lifecycle_status` ∈ {`WITHDRAWN`, `EXPIRED`, `SOLD`} — implementation/routes/feed_events.py:64-70
- §3.6 — revise — **mismatch** — retry backoff parenthetical corrected from "one minute after the first failure, two after the second" to "two minutes after the first failure, four after the second" (impl: `60 · 2^attempt_count` with the post-dispatch count; cross-checked against test_05 expecting 00:02:00 / 00:06:00) — implementation/routes/feed_events.py:86-89
- §3.8 — insert — ambiguity — window creation has no lifecycle-state gate beyond the posture guard (e.g., `DRAFT`/`UNDER_CONTRACT` listings accept windows) — implementation/routes/showings.py:29-52
- §3.8 — insert — ambiguity — feedback submission does not consult window status; a `CANCELLED` window that has ended still accepts its one feedback record — implementation/routes/showings.py:86-118
- §3.8 — revise — ambiguity — a window's feedback is returned as a paginated list holding zero or one record (was "directly readable" with shape unpinned) — implementation/routes/showings.py:121-133
- §3.9 — revise — **mismatch** (mixed edit) — posture after relist recomputes under the ordinary §2.6 rules (`NOT_SYNDICATED` unless breach history forces `DEGRADED`); PRD previously claimed unconditionally `NOT_SYNDICATED`, contradicting §2.6 rule 2 — implementation/routes/listings.py:380-385, implementation/services/derived.py:53-65
- §3.9 — insert — ambiguity (same edit) — relist does not clear `terminal_entered_at`/`terminal_price_cents`; they persist until a later departure re-stamps them — implementation/routes/listings.py:347-385
- §3.9 — insert — ambiguity — relist quote answers for any listing; for one that never left the market: `eligible` false, `cooldown_until` null, and `price_reduction_pct` computed with current `list_price_cents` standing in for `terminal_price_cents` — implementation/routes/listings.py:388-412, implementation/services/derived.py:108-120

**Notable verifications (no change needed):** the §2.9 global validation order is faithfully implemented everywhere (including ownership-before-existence on raw `agent_id` at intake, posture-before-OCC on PATCH/price-change, and field-validity-before-state on mark-ready); all state machines, cascades, display-price/fee/score/breach formulas, error ids + HTTP statuses, envelope shapes, and §4 role assignments match the implementation exactly.
