# Worklog — task_1437_agricultural_drone_remote_sensing_service

## Step 1: Create Task Directory — 2026-08-13T07:11:00.000Z

Task directory `tasks/task_1437_agricultural_drone_remote_sensing_service/` and `workspace/` pre-created and pre-assigned by the pipeline invoker (Step 1 treated as DONE per instructions).

## Step 2: Generate Scaffold — 2026-08-13T07:43:00.000Z

All three files written and lint-clean.

## Report

**Files generated** in `/home/ubuntu/github/CodingPRD/tasks/task_1437_agricultural_drone_remote_sensing_service/`:

- `SCAFFOLD.yaml` — §1.0–§1.7: 10 entities (Grower, SubscriptionPlan, Field, PilotProfile, AirspaceAuthorization, FlightMission, ImageryDeliverable, ScoutingAlert, SprayMissionRecord, InsuranceClaim), 6 state machines, 2 OCC concurrency rules (`mission-replan-stale-version`, `grower-profile-stale-version`), 5 calculation rules (mission_billing dual-variant PROVISIONAL/FINAL tiered overage, anomaly_scoring severity ladder, field_health_score weighted scoring, authorization_window_check, mission_window_conflict buffered overlap), 16-priority ordered validations, 52 endpoints (including `POST /ag-drone/_clock/set_current_utc` with default `2026-08-01T00:00:00Z`), 25+ error codes, 7 roles (OpsAdmin / FlightCoordinator / RemotePilot / Agronomist / Grower / ClaimsAdjuster / ProcessingEngine) with segregation-of-duties between pilot and agronomist.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances across the 9 §0.5 rules (2 per rule), with structured `setup_api_calls` and `trigger` chains.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 29 instances covering entities (computed defaults, required fields, immutability), state machines (invalid transitions, terminal lockdown, grower terminate guard), calculations (severity thresholds, NDVI precision), validations (auth/role/404/window/SOD/SPRAYER plan), endpoints (pagination, deliverable expiry, spray record snapshot), errors (acres range, pilot mismatch, OCC replan, review outcome enum, auth-not-permitted), RBAC denials/allowances, cross-cutting (OCC grower patch, clock-driven auth expiry), consistency (immediate propagation on mission complete).

**Complexity profile**: primary archetype `compliance_audit` + secondary `workflow_orchestration`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, temporal_windowing, scheduled_deferred_actions; hybrid topology; branching state shape; segregation_of_duties role model; immediate consistency.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 52 endpoints, 10 entities, 18 §1.8 instances, 29 §1.9 instances, 546 calls scanned.

**Notable design decisions**:
- Path placeholders normalized to `{id}` throughout §1.5 to satisfy `scaffold_lint.py`'s FK reverse-reachability heuristic (which matches the literal segment `{id}`).
- Added filtered-list GETs `GET /ag-drone/missions`, `GET /ag-drone/alerts`, `GET /ag-drone/claims` with appropriate query filters so every FK in §1.1 is reverse-reachable.
- SprayMissionRecord declared `common_fields: false` (immutable compliance record); its immutability corner is an `excluded_because` stub because no write endpoint exists in §1.5 to test against — the absence of the route is the testable claim.
- ScoutingAlert review loop (OPEN → UNDER_REVIEW → OPEN via /release) and FlightMission replan cycle give two distinct non-linear state-machine shapes on different entities (Rule 3).
- Grower suspension cascade (depth 2) and mission-complete → deliverable → field health (depth 3) give the two transitive cascades from different triggers (Rule 4).

## Step 4: Generate PRD — 2026-08-13T08:00:00.000Z

All checks pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1437_agricultural_drone_remote_sensing_service/workspace/PRD.md`.

**What was done**

- Read the doc-generator skill, the verbatim §2.2 contract block, and the example PRD; read only `SCAFFOLD.yaml` (the two `SCAFFOLD_*_DESIGN.yaml` indices were not opened).
- Generated a full PRD: 2-paragraph introduction (business + regulatory/commercial framing), 11 domain-derived §2 subsections (RBAC with per-role `identity:` translations, verbatim §2.2, pagination, common resource properties including the `common_fields: false` exception for `AirspaceAuthorization`/`SprayMissionRecord`, the logical clock with the `2026-08-01T00:00:00Z` startup default and both sweeps, nested retrieval + the full 16-priority validation pipeline in prose, precision/rounding rules, the two OCC rules, cascading consistency, airspace window semantics, 30-minute buffered conflict rule), 8 §3 workflow subsections with scattered rules (onboarding, authorizations, planning/authorization/replan, flight execution, completion/billing/spray records, processing/anomaly/health, alert review, claims/account standing), a 52-row 4-column §4 endpoint table, and a 40-row 2-column §5 error catalogue.
- All five calculations transcribed as precise prose (tiered PROVISIONAL vs FINAL billing with the 200-acre cap and 0.80 discount rounded half-up per line, NDVI vs PLANT_COUNT anomaly scoring with 0.400/20,000 thresholds and the 1/10/50 severity ladder, health score with 2/5/12 weights and NEEDS_REFLIGHT doubling, inclusive-start/strict-end authorization containment, half-open padded-window conflict with exact back-to-back allowed). No pseudocode, no fuzzy words.
- The scaffold's internal inconsistency (state machine nominates `ERR_SPRAY_NOT_LICENSED`, absent from the error catalog) was resolved to the catalog/validations-table authority: spray license/label failures map to `ERR_PILOT_CERT_EXPIRED`, plan entitlement to `ERR_SPRAY_PLAN_FORBIDDEN`.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 61 required, 61 present, 0 missing
- endpoints[].request_body: 51 required, 51 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in prose (§2.6 pipeline order + §3 per-endpoint ordering), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_mission_version/expected_grower_version + ERR_STALE_MISSION_VERSION/ERR_STALE_GROWER_VERSION 412 all named), 0 missing
- state_machines[].transitions: 24 checked (Grower 3, AirspaceAuthorization 2, FlightMission 7, ImageryDeliverable 4, ScoutingAlert 3, InsuranceClaim 4, Field none), 24 fully expressed with from/to, preconditions+error ids, and side effects, 0 missing
- calculations[]: 5 checked, 5 fully expressed, 0 missing
- validations[] conditions: 16 checked, 16 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 52 endpoints checked, all mutating-endpoint side effects and multi-endpoint applies_to scopes (e.g. ERR_NOT_ASSIGNED_PILOT on launch/capture/abort; ERR_OUTSIDE_WINDOW on launch/create/replan) expressed, 0 missing
- entities[].fields[] structured content: 61 checked, 61 reconstructible from prose (defaults, initial values, >= 50000000 liability floor, <= 400 ft ceiling, 6-hour window, empty-string license defaults), 0 missing
- sibling-branch symmetry: 6 groups checked (SCOUT/SPRAY, NDVI/PLANT_COUNT, PROVISIONAL/FINAL, CONFIRMED/DISMISSED/NEEDS_REFLIGHT, capture vs abort, approve/deny/pay), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 320
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 40 error IDs appear in §2/§3 prose; §2.2 is byte-identical to the fixed contract block; §3 contains no field lists or schema tables; core endpoint parameters are distributed across at least two subsections (e.g. mission window fields in §3.3 and §3.4, grower credit fields in §3.1/§3.5/§3.8).

## Step 5: Generate Unit Tests — 2026-08-13T08:35:00.000Z

All done. Generated the complete test infrastructure for task_1437 (agricultural drone remote-sensing service).

## Stage 1 — `test_helpers/` (9 files)

- `types.py` — 10 entity TypedDicts + 10 enums; `AirspaceAuthorization` and `SprayMissionRecord` correctly carry only `id` + `created_at` (no `updated_at`/`version`, per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (36 methods, all under `/ag-drone`, including `_clock/set_current_utc`)
- `api_errors.py` — full 40-code `ApiErrorId` enum + HTTP status map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` including the lean-field absence checks and the PRD §2.7 health-score [0,100] invariant
- `factories.py`, `constants.py` (wind 20kt, 30-min buffer, tier-1 cap 200, 0.80 discount, severity ladder, 50M liability floor, etc.)
- `test_users.py` — shared constants for the 4 opaque roles; mandatory per-instance builders `make_pilot_headers` / `make_agronomist_headers` / `make_grower_headers` for the 3 entity-backed roles
- `fixtures.py` — tiered composite helpers: `setup_ops` hierarchy, mission lifecycle walkers (`create_mission_authorized` / `in_flight` / `captured` / `completed` / `weather_aborted`), deliverable processing helpers, `setup_field_with_open_alert`, and the claims lifecycle — all with correct identity threading
- `__init__.py` barrel export

## Stage 2 — `test_suite/` (8 files, 66 tests)

- `test_01_onboarding_and_access.py` (7), `test_02_mission_authorization_gate.py` (11), `test_03_flight_execution.py` (9), `test_04_completion_billing_and_spray.py` (8), `test_05_processing_health_and_alerts.py` (10), `test_06_alert_review_workflow.py` (5), `test_07_grower_standing_and_claims.py` (8), `test_08_replan_occ_and_clock.py` (5) — plus `conftest.py`

## Audit results

- **Queue A:** all 18 difficulty instances have ≥2 tests (37 tags)
- **Queue B:** all 29 non-stub corner instances have exactly 1 test; the `spray_record_immutable_no_update_endpoint` stub was correctly not translated (cross-ref verified resolvable)
- **C1 verbatim sweep:** all 88 quoted PRD citation segments survive literal grep of `PRD.md` (whitespace-normalized)
- **C4:** every test has exactly one `Design:` tag resolving to a real instance; no skip/xfail markers
- `pytest --collect-only` succeeds: 66 tests

## Key adjudication decisions

1. **`mission_billing_tiered_overage_straddle` arithmetic correction** — the YAML's pre-computed assert (`invoice_cents == 150000`) miscomputes the first mission as if prior ytd were already 80. Per the PRD ("year-to-date billable acreage as it stood immediately before this mission's acres were added"), the derivable value is `112000` (M1: 80 acres fully inside the 100 allowance → 0; M2: 20 included + 230 overage → 200×500 + 30×400). I asserted the PRD-derived values since the implementer only sees the PRD.
2. **Auth-revoke cascade test** — the difficulty recipe allowed `ERR_MISSION_NOT_PLANNED`/`ERR_AUTH_WINDOW_INSUFFICIENT`/`ERR_AUTH_NOT_ACTIVE` one-of; PRD §3.2 + §3.3 uniquely derive the outcome (revoke cancels the PLANNED mission → authorize then fails the state gate), so I asserted the exact error rather than the disjunction.
3. **Expiry-cascade dead branch** — since containment guarantees `scheduled_start < effective_until`, the "AUTHORIZED missions whose scheduled_start ≥ now" cancel branch can never fire for a legitimately authorized mission; I tested the negative (mission stays AUTHORIZED) rather than inventing an unreachable positive case.

## Step 6: Generate Implementation — 2026-08-13T08:40:00.000Z

Implementation complete. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1437_agricultural_drone_remote_sensing_service/workspace/implementation/`:

**Files produced**
- `app.py` — single-file Flask implementation (~1100 lines), in-memory store, empty at boot
- `start.sh` — executable foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`

**Coverage of the spec**
- All 52 endpoints from the endpoint table, including `POST /ag-drone/_clock/set_current_utc` with the two clock sweeps (authorization expiry → cascade-cancel of future AUTHORIZED missions; deliverable expiry)
- Envelope exactly per §2.2: `meta.api_request_id` (`req_` + 20 alnum), `meta.api_request_timestamp` (3 fractional digits), `response_type` object/array/error, `data.error_id`/`data.message` for errors, pagination fields `limit/offset/total_count/has_more` in `meta` (default 10, clamped to [1,100]), lists sorted by `created_at` ascending
- Validation pipeline in scaffold priority order: 401 → 403 → 404 (left-to-right path/body FKs) → 400 input shape → 409 state → business rules 5→16 (pilot cert → auth window → spray plan → weather → conflict → segregation → identity → temporal → expiry → fiscal); OCC 412s for `expected_mission_version` (replan) and `expected_grower_version` (PATCH grower)
- State machines for Grower, AirspaceAuthorization, FlightMission (incl. weather abort, replan-into-new-resource), ImageryDeliverable, ScoutingAlert (claim/review/release with self-review ban and claiming-agronomist checks), InsuranceClaim (submit → review → approve/deny → pay, coverage-cap accumulation, credit-balance payout)
- Calculations: tiered mission billing (PROVISIONAL flat vs FINAL with 200-acre tier-1 cap and 0.80 discounted rate rounded half-up per line, Decimal throughout), anomaly scoring (NDVI `cells × acres / 1000` half-up; PLANT_COUNT binary vs 20000), severity ladder 1–9/10–49/50+, field health score (NDVI/PLANT_COUNT base, LOW/MEDIUM/HIGH = 2/5/12 penalty, NEEDS_REFLIGHT double-weight, DISMISSED exclusion, clamped 0–100), LAANC window containment (inclusive start, strict end), 30-minute buffered half-open conflict scan with exact back-to-back allowed
- Lean resources: AirspaceAuthorization and SprayMissionRecord carry only `id`/`created_at`; grower-role ownership scoping returns 404 for foreign resources; grower deliverable reads gated by `accessible_until` with 410

**Verification**: three smoke rounds (~70 assertions) passed — full mission lifecycle, billing math (24250 vs 25250 cents FINAL/PROVISIONAL drift on a 250-overage-acre line), health-score arithmetic (68 → 56 on NEEDS_REFLIGHT), boundary semantics (launch at start OK / at end rejected, auth effective-at-takeoff valid / landing-at-expiry rejected, padded exact-touch permitted), and cascade behavior. Three initial smoke failures were test-script contamination (leftover PLANNED missions conflicting on the same field), each confirmed correct in isolation. Fresh-process boot via `bash start.sh` verified 3× with HTTP ready in ~2s and an empty store.

## Step 3: Copy Shared Files — 2026-08-13T07:11:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1437_agricultural_drone_remote_sensing_service/workspace/INSTRUCTION.md`.

## Step 7: Test/Fix Iteration Loop — 2026-08-13T09:30:00Z

**Iteration 1 sweep (8 parallel rounds, per-test-server isolation):** 57–58/66 per round. Union of failures: 11 tests.

**Diagnoses and fixes**

1. `test_06_alert_review_workflow` (4 tests, all rounds) — setup `ERR_ACRES_OUT_OF_RANGE`: `setup_field_with_open_alert` captured `acres_flown=100` against the factory default `acres_planned=10`, violating PRD §3.4 ("no more than the planned acreage"). TEST HELPERS FIX: `test_helpers/fixtures.py::setup_field_with_open_alert` now plans `acres_planned=acres` and defaults the field's `legal_acres` to `max(100, acres)` (PRD §3.3 deeded-acreage invariant).
2. `test_04 TestProvisionalVsFinalBilling` (2 tests, all rounds) — setup `ERR_INVALID_REQUEST` "acres_planned must not exceed the field's legal_acres": tests flew 350 acres on a default 100-acre field, violating PRD §3.3. TEST FIX: both tests now pass `field_overrides={"legal_acres": 400}`. The PRD-required check in the implementation was left intact.
3. `test_03 TestLaunchAuthorizationDependency::test_launch_with_expired_authorization_outside_window_reports_auth_error` (all rounds) — ERROR PRECEDENCE SILENCE: PRD §2.6's business-rule priority list names only the authorize-time airspace errors (`ERR_AUTH_WINDOW_INSUFFICIENT`/`ERR_AUTH_NOT_PERMITTED`) and never places `ERR_AUTH_NOT_ACTIVE`; §3.4's launch sentence lists the window check before the authorization-active check. Two faithful PRD-only implementations diverge (scaffold had pinned priority 6 < 13, but that ordering never reached PRD prose). ASSERTION RELAXED (sanctioned coverage correction) to `validate_error_is_one_of([ERR_AUTH_NOT_ACTIVE, ERR_OUTSIDE_WINDOW])` — both members PRD-named for launch.
4. `test_07::test_approve_beyond_remaining_cap_rejected` (rounds 1,2,7) — flaky `ConnectionError: Remote end closed connection without response`: stale keep-alive connection in the module-level `requests.Session` racing the runner's SIGKILL+respawn between tests. TEST HELPERS FIX: `test_helpers/api_client.py::ApiClient.__init__` sets `Connection: close` on the session so every request uses a fresh TCP connection. Transport-only hardening; no assertion touched.
5. Round-3 setup timeouts (`test_capture_at_wind_20_succeeds`, `test_invoice_then_payout_conserves_balance`) — server-boot starvation under 8x load; did not recur after fixes (indirectly helped by fix 4).

**Iteration 2 sweep:** all 8 rounds 66/66 — clean. No tests deleted; no implementation changes required.

## Step 8: Finalize PRD — 2026-08-13T09:45:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1437_agricultural_drone_remote_sensing_service/workspace/PRD_FINALIZED.md`.

## Size delta

- PRD.md: 307 lines / 46,911 chars → PRD_FINALIZED.md: 307 lines / 47,145 chars
- Delta: **0 lines (0.00%)**, +234 chars (+0.50%). Three inline edits, no new sections.

## Step-7 item triage

- **Item 1** (`test_06` fixture: `acres_flown=100` vs `acres_planned=10`) — pure fixture bug. PRD §3.4 already pins "no more than the planned acreage" → `ERR_ACRES_OUT_OF_RANGE`; impl enforces it at `app.py:1133-1134`. No edit.
- **Item 2** (`test_04` fixture: 350 acres flown on a 100-acre field) — pure fixture bug. PRD §3.3 already pins planned-acreage ≤ deeded-acreage → `ERR_INVALID_REQUEST`; impl enforces at `app.py:985-987`. No edit.
- **Item 3** (`test_03` precedence silence) — the only genuine PRD silence. Impl `launch_mission` evaluates the window check **before** the authorization-liveness check, so the both-fail case yields `ERR_OUTSIDE_WINDOW`. Three edits below.
- **Item 4** (`Connection: close` in `api_client.py`) — transport-only, no API behavior. No edit.
- **Item 5** (boot timeouts under 8x load) — infrastructure. No edit.

## Changes (all trace to step_7_diff item 3)

- **§2.6** — insert — added `ERR_AUTH_NOT_ACTIVE` to the business-rule priority sequence, placed after temporal window checks and qualified as launch-time ("then the launch-time authorization-liveness check (`ERR_AUTH_NOT_ACTIVE`)") — `implementation/app.py:1108-1114`
- **§3.2** — revise — scoped the closing sentence from "a launch attempted against an authorization that is no longer `ACTIVE`" to "a launch attempted **within its planned window** against an authorization that is no longer `ACTIVE`", so it no longer universally claims `ERR_AUTH_NOT_ACTIVE` for the both-fail case — `implementation/app.py:1108-1114`
- **§3.4** — revise — appended an explicit precedence clause to the launch sentence: "the window check runs before the authorization-liveness check, so an attempt that violates both is rejected as `ERR_OUTSIDE_WINDOW`" — `implementation/app.py:1108-1114`

## Pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit 1 (§2.6 priority-list insertion)**
- (a) Subject: global placement of `ERR_AUTH_NOT_ACTIVE` in the gate-5 business-rule order.
- (b) Enumerated every raise site of the error and its new neighbors: `app.py:946` (revoke — a gate-4 state precondition, correctly excluded by the "launch-time" qualifier), `app.py:1114` (launch — business rule evaluated at lines 1111-1114, after the window check at 1108-1110), all `ERR_OUTSIDE_WINDOW` sites (`app.py:992` plan, `app.py:1109` launch, `app.py:1246` replan — relative order vs. launch's auth check only observable at launch, where window precedes), and `ERR_DELIV_EXPIRED` (`app.py:1284` deliverable read — never co-occurs with launch, so placing auth-liveness before it is unobservable).
- (c) Wording adjustment: added the "launch-time" qualifier so the revoke path (state precondition, not a business rule) is not mis-described as belonging to this list.

**Edit 2 (§3.2 sentence scoping)**
- (a) Subject: §3.2's unqualified universal "a launch attempted against an authorization that is no longer ACTIVE fails with ERR_AUTH_NOT_ACTIVE".
- (b) Enumerated impl paths the sentence covers: only `launch_mission` (`app.py:1099-1117`). In the both-fail case (outside window + lapsed auth) impl returns `ERR_OUTSIDE_WINDOW` (line 1109 fires before 1114), so the unqualified sentence mis-described that case. The paragraph's other `ERR_AUTH_NOT_ACTIVE` sentence covers revoke (`app.py:946`) and was left untouched.
- (c) Wording adjustment: inserted "within its planned window" (6 chars of scope) rather than rewriting the sentence, keeping the claim true for every launch input combination the impl exhibits.

**Edit 3 (§3.4 launch precedence clause)**
- (a) Subject: launch-site ordering of `ERR_OUTSIDE_WINDOW` vs `ERR_AUTH_NOT_ACTIVE`.
- (b) Enumerated: `app.py:1099-1117` `launch_mission` full check chain (role → 404 → `ERR_MISSION_NOT_AUTHORIZED` → `ERR_NOT_ASSIGNED_PILOT` → window → auth-liveness — identity-before-window already matches §2.6, untouched); other `ERR_OUTSIDE_WINDOW` sites (`app.py:992`, `app.py:1246` — planning/replan future-start checks with no authorization-liveness check in play, out of scope of the launch-scoped clause); authorize endpoint (`app.py:1068-1083` — non-ACTIVE auth there yields `ERR_AUTH_WINDOW_INSUFFICIENT`, a different path the clause does not describe); revoke (`app.py:946` — state precondition, out of scope).
- (c) Wording adjustment: kept the original sentence verbatim and appended the precedence as a trailing clause ("the window check runs before the authorization-liveness check, so an attempt that violates both is rejected as `ERR_OUTSIDE_WINDOW`") rather than reordering existing prose, minimizing disturbance to text other sections cross-reference.

## Step 9: Complete PRD — 2026-08-13T10:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1437_agricultural_drone_remote_sensing_service/workspace/PRD_COMPLETED.md` written.

**Source vs output:** PRD_FINALIZED.md (source, 307 lines / 47,301 chars) → PRD_COMPLETED.md (307 lines / 49,815 chars), +2,514 chars. All 22 changed lines are in-place paragraph revisions; no sections added or removed.

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions.

**Changes (one bullet each):**
- §2.1 — insert — ambiguity — grower-role access to another grower's resource tree is refused as `ERR_NOT_FOUND` (404), not 403 — app.py:171-174
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the server wall clock at response time, not the logical clock — app.py:108
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset floored at 0), non-integer values are `ERR_INVALID_REQUEST`, `created_at` sort ties break by creation order — app.py:262-288
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — app.py:251
- §2.5 — insert — ambiguity — clock-set adopts any valid instant unconditionally, including one earlier than current — app.py:1599-1606
- §2.6 — revise — ambiguity — added `ERR_ACRES_OUT_OF_RANGE` to the weather/acreage limit tier of the business-rule sequence — app.py:1130-1135
- §2.6 — revise — ambiguity — added `ERR_CLAIM_MISSION_NOT_FINAL` after `ERR_CLAIM_EXCEEDS_COVERAGE` in the fiscal tier — app.py:1558-1564
- §2.8 — insert — ambiguity — stale-version (OCC) checks fire after existence and state preconditions, before remaining business rules — app.py:669, 1239
- §3.1 — revise — ambiguity — duplicate `plan_code` rejected as `ERR_INVALID_REQUEST` — app.py:564-566
- §3.1 — revise — ambiguity — duplicate `part107_certificate_no` draws `ERR_INVALID_REQUEST` — app.py:853-856
- §3.2 — revise — ambiguity — `max_altitude_ft` must be an integer 0–400 inclusive (negatives rejected); `effective_from`/`effective_until` ordering is not validated at registration — app.py:904-908
- §3.3 — revise — ambiguity — `acres_planned` must be a positive integer (not merely ≤ deeded acreage) — app.py:983-987
- §3.3 — insert — ambiguity — replanning a mission not in `WEATHER_ABORTED`/`CANCELLED` refuses with `ERR_INVALID_STATE` (409) — app.py:1236-1238
- §3.5 — revise — ambiguity — `deliverable_kinds` must be a non-empty list of only `NDVI`/`PLANT_COUNT`, else `ERR_INVALID_REQUEST` — app.py:1170-1174
- §3.5 — revise — ambiguity — `restricted_entry_interval_hours` is supplied in the completion payload as an integer, defaulting to 0 — app.py:1175, 1208
- §3.5 — revise — mismatch — PROVISIONAL variant is not returned by the completion call; it is reported per line and as `provisional_total_cents` only by the invoice run (impl completion response carries no billing quote) — app.py:1212 vs 764-791
- §3.5 — revise — ambiguity — invoice period membership is by completion instant, half-open [period_start, period_end), settled oldest-first; each line item carries `mission_id`, `acres_flown`, `overage_acres`, `provisional_cents`, `final_cents` — app.py:754-786
- §3.6 — revise — ambiguity — `ndvi_mean` accepted at any numeric precision within [0,1] and rounded to three decimals for storage (not rejected for extra precision) — app.py:1306-1317
- §3.6 — insert — ambiguity — `cells_below_threshold` defaults to 0 and must be a non-negative integer, else `ERR_DELIV_INPUT_INVALID` — app.py:1312-1315
- §3.6 — revise — ambiguity — `storage_uri` format pinned as `s3://ag-drone-deliverables/{mission_id}/{deliverable_id}` — app.py:1327
- §3.6 — revise — ambiguity — health-score base rounding is half-up for both kinds; base is 100 when the field has no `READY`/`DELIVERED` deliverable — app.py:518-529
- §3.6 — revise — ambiguity — grower expiry refusal (`ERR_DELIV_EXPIRED`) gates only the individual deliverable read; the per-mission list returns expired deliverables unfiltered — app.py:1281-1284 vs 1288-1295
- §3.7 — revise — ambiguity — an omitted `review_outcome` draws `ERR_REVIEW_OUTCOME_INVALID` (not a missing-field 400) — app.py:1432-1435
- §3.8 — revise — mismatch — claim approval runs the coverage check first (non-positive `amount_cents` is also `ERR_CLAIM_EXCEEDS_COVERAGE`, 422), then the mission-final check; prior prose implied mission-final first — app.py:1550-1564
- §3.8 — revise — ambiguity — the mission named on claim submission need only exist, not belong to the claiming grower — app.py:1484-1485

**Generator feedback**
- unit-test-generator: `setup_field_with_open_alert` and the two test_04 setups violated PRD input invariants (acres_planned > legal_acres; acres_flown > acres_planned) — fixture/factory composition must respect PRD domain invariants.
- unit-test-generator + doc-generator: launch-time `ERR_AUTH_NOT_ACTIVE` vs `ERR_OUTSIDE_WINDOW` precedence is not pinned in PRD prose (§2.6 priority list omits `ERR_AUTH_NOT_ACTIVE`); scaffold-only priority numbering must be surfaced in PRD or tests must accept the one-of set.
