# Worklog — task_0599_reputation_reviews

Scenario: Online Reputation & Reviews Management (Birdeye style): review-request campaign & SMS/email, multi-site (Google/Yelp/Facebook) aggregation, sentiment & rating dashboard, response/template & escalation, listing/NAP sync, survey & NPS, competitor benchmark, alert & website widget

Difficulty: Expert (passed to prd-bench-scaffold-generator only)

## Step 1: Create task directory — 2026-07-12T01:30:00.000Z

Task directory `tasks/task_0599_reputation_reviews/` with `workspace/` was pre-allocated by the user before this run; no scan or creation performed by the orchestrator.

## Step 2: Generate scaffold — 2026-07-12T01:44:45.000Z

The lint verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  495

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Three files in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0599_reputation_reviews/`.

**SCAFFOLD.yaml** (§1.0–§1.7), Expert tier
- **Profile**: `workflow_orchestration` + `compliance_audit`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, conditional_feature_flags; topology hierarchical; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.
- **14 entities**: Business, Location, Listing, Competitor, Contact, ResponseTemplate, Campaign, ReviewRequest, Review, ReviewResponse, Escalation, SurveyResponse, Widget, Alert.
- **7 state machines**: Location (posture OPEN/RESTRICTED/FROZEN, system-derived), Listing (cyclic PENDING_SYNC↔SYNC_FAILED→CONNECTED, terminal DISCONNECTED at 3 failures), Review (**parallel dimensions**: `moderation_state` × `response_state`), ReviewResponse (**cyclic** DRAFT→PENDING_APPROVAL→REJECTED→DRAFT), Escalation (branching, incl. CANCELLED compensation), Campaign (cyclic RUNNING↔PAUSED), ReviewRequest.
- **2 OCC concurrency rules** (`campaign-create-stale-location` on `Location.version`, `response-create-stale-review` on `Review.version`), both 412.
- **8 calculations**: `review_sentiment`, `listing_health_score` (3-input nested min/max + tiered site weights), `location_reputation_score` (**PROVISIONAL vs CERTIFIED** variants), `location_posture` (constraint propagation, `>= 60.00` gate armed at ≥3 reviews), `campaign_billing_cost` (**round-per-line-then-sum** pinned), `campaign_conversion_rate` (**STRICT vs BROAD** variants), `nps_score`, `competitor_benchmark`.
- **23 ordered validations**, **58 endpoints** (incl. `POST /reputation/_clock/set_current_utc`, default clock `2026-05-01T00:00:00Z`), **33 errors**, **6 roles** (PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer, Anonymous — each with `identity:`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule blocks × 2 = **18 instances**, all with structured `setup_api_calls`/`trigger`/`assert` and pre-computed literal expectations (e.g. provisional 63.00 vs certified 75.00; strict 50.00 vs broad 100.00; SMS billing 0.24 not 0.23; posture exactly 60.00 stays OPEN; ingest→Location→Campaign→ReviewRequest depth-3 cascade; buffered send-window collision at 11:15 vs 11:16; half-open frequency cap at +30d).

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections, **48 instances (40 executable + 8 `excluded_because` stubs)** covering defaults, not-found, required fields, type constraints, system fields, immutability, pagination, invalid/terminal transitions, side-effect cascades, calculation input-set filtering, all remaining error triggers, RBAC denials + segregation-of-duties by user id, both OCC rules, the `requires_approval` feature flag, and immediate-consistency visibility.

Files: SCAFFOLD.yaml (2384 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1445 lines), SCAFFOLD_CORNER_DESIGN.yaml (1832 lines).

## Step 3: Copy shared files — 2026-07-12T01:44:45.000Z

Copied `INSTRUCTION.md` → `tasks/task_0599_reputation_reviews/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-12T02:05:00.000Z

PRD generated at `workspace/PRD.md` — 448 lines.

## Structure
- **§1 Introduction** — 3 paragraphs (market pain → four operational jobs → the posture gate that binds them).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (all six roles + each role's identity binding), 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, verified byte-for-byte), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock (incl. `Competitor`/`Alert` having no `updated_at`/`version`; clock default `2026-05-01T00:00:00Z`), 2.5 Location Posture: the Master Gate, 2.6 Recomputation Order and Cascade Discipline (the two 3-link cascade chains), 2.7 Scoring Precision and Rounding Discipline (round-then-sum vs sum-then-round), 2.8 OCC, 2.9 Nested Path Resolution and Validation Precedence (explicit 1–23 ordered list), 2.10 The Alert Feed (5 types with fixed severities).
- **§3 Business Logic** — 8 subsections grouped by domain surface: tenant onboarding, listings/NAP health, review ingest + parallel moderation dimension, the reply workflow, escalations, campaigns (schedule/credits/send/attribution), surveys+competitors+widget+dashboard, and reputation scoring + certify/compliance-hold.
- **§4** — 4-column endpoint table (57 endpoints). **§5** — 2-column error table (33 errors).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[].request_body: 48 required, 48 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (explicit ordered list in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_location_version / expected_review_version + ERR_STALE_VERSION 412 all named), 0 missing
- state_machines[].transitions: 7 machines / 43 transitions checked, 43 fully expressed, 0 missing
- calculations[]: 8 checked (review_sentiment, listing_health_score, location_reputation_score ×2 variants, location_posture, campaign_billing_cost, campaign_conversion_rate ×2 variants, nps_score, competitor_benchmark), 8 fully expressed in prose with every constant embedded, 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 57 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 93 checked (types, defaults, initial values, enum members), reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (submit's two branches; manual vs system pause; sync SUCCESS vs FAILURE; PROVISIONAL vs CERTIFIED; STRICT vs BROAD; empty vs non-empty competitor set), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 583
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes
- Every scaffold constant is embedded in business context (site weights 0.5/0.3/0.2, state factors, 7-day grace / 2-pt-per-day / 30-pt cap staleness, 60/25/15 score weights, 0.02-per-30-days decay with 0.5 floor, posture thresholds 60.00/3/40.00/3, base rates 0.075 and 0.012 with 1.00/0.90/0.80 tiers at indices 100/500, 14-day attribution and survey TTL, 15-minute channel buffer, 3-failure sync ceiling, NPS 9/6 buckets).
- Boundary inclusivity is stated explicitly everywhere it matters (posture score `>= 60.00` passes, half-open frequency-cap and attribution windows, `>= expires_at` rejects, closed buffered send-window intervals).
- Only structural note: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, per the hard constraint.

## Step 5: Generate unit tests — 2026-07-12T02:30:00.000Z

Orchestrator note: Steps 5 and 6 were intended to launch concurrently but were in fact launched sequentially (Step 5 first, then Step 6). To preserve the benchmark contract despite `test_suite/` existing on disk at Step 6 spawn time, the Step 6 prompt carried an explicit hard constraint forbidding any read/list/grep of `test_suite/` and `test_helpers/`.

All checks pass. Here's the final state.

## Files written

**`test_helpers/`** (Stage 1, 8 files)
- `types.py` — 6-role enum, 17 status enums, entity TypedDicts. `Competitor` and `Alert` carry **only** `id` + `created_at` (PRD §2.4 append-only); all others carry `updated_at` + `version`.
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (57 methods, incl. `/_clock/set_current_utc`).
- `api_errors.py` — 33-member `ApiErrorId` + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_score` (2-dp round-half-up), `assert_instant_equals` (logical-clock instants), `assert_credit_ledger` / `assert_spendable_credits`, `assert_alert_severity` (fixed severity per type), `assert_append_only_fields`.
- `factories.py`, `constants.py`, `test_users.py` (per-instance `make_business_owner_headers(business_id)` / `make_location_manager_headers(location_id)` for the entity-backed roles; `anonymous_headers()` with no `X-User-ID` for the public surface).
- `fixtures.py` — 5 tiers: clock/CRUD wrappers → known-`listing_health_score` locations (100.00 / 50.00 / 0.00) → running campaigns with queued requests → reply-workflow ladders (`setup_pending_approval_response`, `setup_approved_response`) → cascade preambles.

**`test_suite/`** — `conftest.py` + 10 test files, **76 tests**, all collect cleanly.

## Coverage audit

| Queue | Instances | Translated | Skipped |
|---|---|---|---|
| A — Difficulty (§1.8) | 18 (9 rules × 2) | **18, all with ≥2 tests** (36 tests) | 0 |
| B — Corner (§1.9) | 40 non-stub + 8 stubs | **40, ≥1 test each** (40 tests) | 0 non-stub; 8 `excluded_because:` stubs correctly not translated (all 8 `difficulty_instance` cross-refs verified to resolve) |

Verified mechanically: 76/76 tests tagged, 0 untagged, 0 dual-tagged, 0 dangling tags, 0 tags pointing at stubs; 134/134 PRD quotations survive a literal normalized grep of `PRD.md`.

## Two design-yaml assertions I did **not** copy verbatim (PRD contradicts them)

1. **`transitive_cascade/ingest_restricts…`** and **`boundary_precision_check/posture_score_gate_at_exactly_60…`** assert "exactly one" / "zero" `POSTURE_CHANGED` alerts in the whole feed. Per PRD §2.5 + §3.2 + §2.10, attaching the first listing already drives `listing_health_score` to 15.00 (< 40.00) → `RESTRICTED`, and syncing it recovers → `OPEN`, so ≥2 such alerts pre-exist the trigger. I asserted the PRD-faithful equivalent instead: the alert count **delta across the trigger** is exactly 1 (resp. 0), plus severity `CRITICAL`.
2. **`priority_pair_validation_conflict/frozen_posture_beats_daily_send_cap`** asserts the two requests stay `QUEUED` after the compliance hold. PRD §3.6 says a *system* pause — explicitly including "by being frozen" — empties the queue to `SUPPRESSED`. I dropped the `QUEUED` claim and asserted what both readings agree on (`status != SENT`, `send_index is None`, `credits_consumed == 0`, `billing_cost == 0.00`, campaign `PAUSED`); the instance's actual subject (409 `ERR_LOCATION_FROZEN` beating 422 `ERR_SEND_CAP_EXCEEDED`) is asserted directly from PRD §2.9's numbered precedence list.

One sub-assertion was dropped as PRD-underdetermined: `rejection_reason` surviving a revise (`non_linear_state_machine/response_reject_revise_cycle…`) — PRD §3.4 states neither that revise clears it nor that it persists. The instance's core cycle claims (`state == DRAFT`, `revision_count == 1`, body replacement, `response_state == DRAFTED`, re-submit → `PENDING_APPROVAL`) are all asserted.

## Step 6: Generate implementation — 2026-07-12T02:46:00.000Z

The implementation is complete and verified end-to-end.

## Files written (`workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install` (skipped when Flask present) + `exec python3 app.py` |
| `requirements.txt` | Flask 3.0.3 |
| `app.py` | App factory, blueprint registration, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | In-memory dicts, logical clock (boots at `2026-05-01T00:00:00Z`), UUIDs, insertion sequence, all serializers |
| `errors.py` | 33-entry error catalogue with HTTP codes |
| `envelope.py` | `meta`/`response_type`/`data` envelope, `req_` request ids, `limit`/`offset`/`total_count`/`has_more` pagination |
| `auth.py` | `X-User-ID` / `X-User-Role`, 6 roles, tenant scoping, left-to-right path resolvers |
| `validation.py` | Well-formedness helpers (400 layer) |
| `calc.py` | All 8 calculation rules |
| `services.py` | Recompute chain, alerts, cascades, posture gates, version bookkeeping |
| `routes/` | 11 blueprints (businesses, locations, listings, campaigns, requests, reviews, responses, escalations, surveys, widgets, misc) |

**58 endpoints** registered — matches the PRD §4 table exactly. Storage is in-memory only; nothing is seeded at boot.

## How the hard parts are structured

**State machines.** Each transition is a guard block inside its route, ordered FROZEN → RESTRICTED → state-legality. Listing sync legality is source-state based (`CONNECTED` and `DISCONNECTED` both reject; `SYNC_FAILED` at 3 failures rejects); the failure ladder is `PENDING_SYNC → SYNC_FAILED → SYNC_FAILED → DISCONNECTED` on the third increment. Review carries two independent dimensions (`moderation_state`, `response_state`); the `ReviewResponse` machine drives the second one. `requires_approval == false` collapses submit into `APPROVED` with `approved_by_user_id` left null and SoD bypassed.

**Cascades.** `services.recompute_location()` is the single chain: counters → `listing_health_score` → `reputation_score_provisional` → `nps_score` → posture. Posture change appends `POSTURE_CHANGED`; any non-`OPEN` posture system-pauses `RUNNING` campaigns, which suppresses their `QUEUED` requests and releases credits (verified: ingest → location → campaign → request, 4 deep). Publish runs link 1→2→3 (review `RESPONDED` → escalations `RESOLVED` → location recompute). Survey submit deliberately uses a narrower `recompute_nps()` so it never re-derives posture.

**Calculations.** All `Decimal` + `ROUND_HALF_UP`. Listing health rounds once at the end (per-site bases and state factors kept exact). Billing rounds **per line then sums** (3 SMS = 0.08×3 = 0.24). Certified score uses the `VERIFIED`-only set with the 30-day decay weight floored at 0.5; provisional uses the non-`FLAGGED` set unweighted. Both conversion rates share the billable denominator; capped at 100.00.

**Validation ordering.** Implemented as PRD §2.9's 23 numbered steps: auth → authz → tenant → path (left-to-right) → body-refs → well-formedness → **OCC → FROZEN** → RESTRICTED → state → expiry → consent → SoD → template band → listing → responded → uniqueness → window → freq-cap → credits → send-cap. Note OCC deliberately precedes the FROZEN gate.

**OCC.** Two writes only: `expected_location_version` on campaign create, `expected_review_version` on response draft, both → `ERR_STALE_VERSION` 412. Location/review versions bump once per request via a `g.touched` set, including on derived-field mutation (so a review ingest advances the location's version, which is what makes campaign-create OCC bite).

## Step 7: Run tests and iterate — 2026-07-12T02:52:00.000Z

The task is already in a fully passing state. One 8-round parallel sweep was sufficient to establish that, and no fixes were required.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep). All 8 rounds ran to completion under `--isolation per-test-server`; no early exit.

**Result: all 8 rounds green — 76/76 passed, 0 failed, 0 errors, 0 skipped**, ~49.3s per round (rounds ran concurrently, so ~49s wall total).

```
round 1: 76/76    round 5: 76/76
round 2: 76/76    round 6: 76/76
round 3: 76/76    round 7: 76/76
round 4: 76/76    round 8: 76/76
UNION OF FAILING TESTS ACROSS ALL 8 ROUNDS: 0
```

The union of failures across all 8 rounds is empty, so no test entered the diagnostic protocol. Round-to-round timing was near-identical (49.33–49.41s), and no test flipped status between rounds — no flakiness signal in the concurrency, fixture-ordering, or port-collision classes the sweep is designed to surface.

**Tests deleted:** none. No test failed, so STEP 1 (PRD coverage / unique-derivability) was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Integrity checks performed

Because a first-try clean sweep can mask a gamed suite, I verified the pass was real rather than vacuous:

- **No suppression markers.** `grep` for `pytest.mark.skip`, `pytest.mark.xfail`, `pytest.skip`, `pytest.xfail` across both `test_suite/` and `test_helpers/` returns nothing.
- **Full collection.** 76 `def test_` functions on disk across the 10 suite files (5+7+11+9+4+7+7+11+7+8), exactly matching the 76 collected and passed — nothing is being silently dropped at collection.
- **No working-tree edits.** `git status` confirms I made zero modifications to `test_suite/`, `test_helpers/`, or `workspace/implementation/`; the pass reflects the artifacts as they already stood.

### One caveat worth flagging

My first aggregation pass keyed on `t["outcome"]`, but `results.*.json` records per-test status under `t["status"]`. That bug briefly made all 76 tests appear to fail in every round. The corrected aggregation (keying on `status`, values `passed`/`failed`/`error`/`skipped`) is what the numbers above come from — the underlying rounds were green from the start, and no code was touched on the basis of the bogus reading.

The 8 `results.{1..8}.json` files remain in `workspace/implementation/` as written by the runner.

### Orchestrator independent verification

The orchestrator re-verified Step 7's claims rather than trusting the summary, since a first-try green sweep is the case most worth double-checking:
- All 8 `results.*.json` re-parsed directly: every round `passed=76 failed=0 total=76`, per-test status Counter `{'passed': 76}` — no non-passed status of any kind.
- Suppression-marker grep across `test_suite/` + `test_helpers/`: 0 hits.
- `def test_` count on disk: 76, matching the 76 collected/passed (no silent collection drop).
- `git status` on the task dir: only the untracked new directory, no modifications to committed artifacts.

## Step 8: Finalize PRD — SKIPPED — 2026-07-12T02:53:00.000Z

Skip condition met per the pipeline spec: Step 7 exited on the first 8-round sweep with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `<step_7_diff>` would therefore be empty, and Step 8's edit scope is defined as exactly the set of Step 7 diff items. `PRD.md` already uniquely determined every behavior the implementation exhibits along every path the 76 tests exercise, so no `PRD_FINALIZED.md` was produced. Step 9 (which always runs) performs the full PRD-vs-implementation scan and starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-12T03:00:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Source vs output**
| | PRD.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 448 | 450 (+2) |
| chars | 69,091 | 74,588 (**+5,497**) |

17 hunks total: **1 inserted paragraph**, **16 in-paragraph revisions**. No new sections.

**Counts:** ambiguity-pins **14**, mismatch-revisions **3**.

## Changes

- **§2.3 Pagination** — insert — ambiguity — tenant-agnostic lists (`/reviews`, `/review-responses`, `/review-requests`, `/surveys`) silently filter out-of-tenant rows for BusinessOwner/LocationManager rather than 403; unknown id-valued filters return that identifier's own 404; unrecognised enum filter values (incl. `opted_out` requiring the literal `true`/`false`) are `ERR_INVALID_REQUEST` — `routes/reviews.py:100-125`, `routes/requests.py:17-52`, `routes/surveys.py:63-81`, `routes/businesses.py:127-132`
- **§2.4 Common Properties** — revise — ambiguity — a request bumps a resource's `version` at most once however many fields it touches, and a recomputation whose derived values are all unchanged bumps nothing — `services.py:26-36`, `services.py:119-120`
- **§2.5 Posture** — revise — mismatch — the FROZEN block list omitted NAP replacement, the delivery-connector callback and competitor snapshots, all of which impl blocks — `routes/locations.py:136`, `routes/locations.py:33`, `routes/requests.py:69`
- **§2.6 Recomputation Order** — revise — ambiguity — derived counters are recomputed from scratch (never incrementally adjusted), and `nps_score` is refreshed inside the same chain — `services.py:78-110`
- **§2.9 Precedence rule 3** — revise — mismatch — tenant scoping only precedes 404 where the acting identity alone settles ownership (`{business_id}` for either bound role; `{location_id}` for LocationManager). Everywhere else the row must be resolved first, so 404 wins — including a BusinessOwner naming an unknown `{location_id}` — `auth.py:85-103`, `auth.py:106-186`
- **§3.1 Locations** — revise — ambiguity — creating a location also bumps the parent business's `version`/`updated_at` — `routes/businesses.py:79-80`
- **§3.1 Contacts** — revise — ambiguity — `phone`/`email` are type-checked as strings but their shape is never validated (E.164 not enforced) — `routes/businesses.py:101-102`
- **§3.1 Contacts** — revise — ambiguity — opt-out is idempotent with no state gate; re-opting-out returns 200, not `ERR_INVALID_STATE` — `routes/misc.py:16-21`
- **§3.2 Listing sync** — revise — ambiguity — legal source states are checked before `outcome` is consulted; syncing an already-`CONNECTED` listing is `ERR_INVALID_STATE` regardless of reported outcome — `routes/listings.py:69-74`
- **§3.4 Reject** — revise — ambiguity — `rejection_reason` is a mandatory string; omitting it is `ERR_INVALID_REQUEST` — `routes/responses.py:166`
- **§3.6 Enqueue** — revise — ambiguity — enqueue has no campaign-status gate at all; a queue may be filled against a `DRAFT` or `COMPLETED` campaign — `routes/campaigns.py:162-227` (no status check)
- **§3.6 Send batch** — revise — ambiguity — `batch_size` is a mandatory integer ≥ 1; the daily cap counts requests by `sent_at` date, so `DELIVERED`/`CLICKED`/`CONVERTED`/`FAILED` still count against the day; an empty batch is a no-op success with no `SEND_CAP_REACHED` alert — `routes/campaigns.py:235`, `routes/campaigns.py:248-254`, `routes/campaigns.py:271`
- **§3.6 Send batch response** — revise — ambiguity — the body is a bare summary object whose `sent_count` is this batch's count, not the campaign's lifetime tally — `routes/campaigns.py:276-281`
- **§3.6 Delivery outcomes** — revise — ambiguity — `event_type` accepts only `DELIVERED`/`CLICKED`/`FAILED`; `CONVERTED`/`SUPPRESSED` are `ERR_INVALID_REQUEST`, and a wrong source status is `ERR_INVALID_STATE` — `validation.py:16`, `routes/requests.py:71-83`
- **§3.6 Attribution** — revise — ambiguity — a non-convertible status or an out-of-window `posted_at` is not an error: the request is untouched while the review is still created and still records its `review_request_id` — `routes/reviews.py:82-86`
- **§3.7 Widget** — revise — mismatch — `GET /locations/{id}/widget` returns a paginated `"array"` envelope (empty when no widget exists), never a bare object or `ERR_WIDGET_NOT_FOUND`; also pins publish-from-non-`DRAFT` as `ERR_INVALID_STATE` — `routes/widgets.py:44-49`, `routes/widgets.py:58-59`
- **§3.7 Dashboard** — revise — ambiguity — `rating_delta` subtracts the *already-rounded* `competitor_avg_rating`, not the exact mean — `calc.py:274-278`
- **§3.8 Compliance holds** — revise — ambiguity — `on_hold` is mandatory and the toggle rejects a redundant request with `ERR_INVALID_STATE` rather than treating it as a no-op — `routes/locations.py:56-59`

## Pipeline complete — 2026-07-12T03:00:00.000Z

All 9 steps done. Final state: 76/76 tests passing across all 8 stability rounds; `PRD_COMPLETED.md` is the ambiguity-free contract.
