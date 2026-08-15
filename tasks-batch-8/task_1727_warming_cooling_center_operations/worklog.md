# Worklog — task_1727_warming_cooling_center_operations

## Step 1: Create Task Directory — 2026-08-14T11:34:23.000Z

Task directory `tasks/task_1727_warming_cooling_center_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command (Step 1 treated as DONE; no index scan performed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-14T12:36:44.000Z

All three scaffold artifacts are generated, lint-clean, and cross-audited. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` (§1.9)

## Counts
- **Entities: 14** — Episode, WeatherReading (immutable event log, `common_fields: false`), Site, SiteActivation (computed capacity/coverage/stock fields), StaffMember, Shift, Guest, GuestStay, Vehicle, TransportDispatch, Donation, MealService, Incident, AfterActionReport
- **State machines: 9** (all entities except Site/StaffMember/Vehicle/Guest/WeatherReading); Episode is cyclic (STANDBY↔ACTIVATING stand-down loop, ACTIVE↔DEACTIVATING re-surge loop), GuestStay forks with divergent side effects (dispatch-reserved vs walk-in birth; check-out/eject/transfer exits)
- **Endpoints: 56** (incl. `POST /api/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- **Errors: 30** (top of the Expert band), **calculations: 9**, **validations: 9 priority tiers**, **roles: 6** (segregation-of-duties model), **OCC concurrency rules: 2** (Episode extensions, Site PATCH)

## Difficulty-design coverage (§1.8: 19 instances, all 9 rules ≥2)
- **dual_variant_calc**: bed-nights provisional-vs-final on GuestStay (2 vs null in-progress); meal stock on_hand-vs-projected on Donation/MealService — different entity domains
- **combinatorial_formula**: mode (a) nested-min pet-branch dispatch reservation gate; mode (b) round-per-service-then-sum meal planning (12 vs the forbidden 11) — different modes
- **non_linear_state_machine**: Episode double-cycle; GuestStay branching forks — different entities
- **transitive_cascade**: depth-3 deactivation chain (Episode→SiteActivation→GuestStay→TransportDispatch auto-cancel); depth-2 behavioral-escalation ejection chain — different triggers
- **priority_pair_validation_conflict**: safety-vs-fiscal (medical hold beats no-bed); state-vs-constraint (cancelled shift beats overlap) — different category pairs
- **boundary_precision_check** (3 instances): heat-index exactly-at-threshold + exactly-60-min run via evaluate; beds_free 0-vs-1 via intake; 06:00-exclusive overnight end via open — distinct metrics and endpoints
- **cross_entity_state_dependency**: GuestStay→SiteActivation intake gate; AfterActionReport→Incident submit gate — different pairs
- **resource_temporal_overlap**: StaffMember half-open shifts (adjacency allowed) vs Vehicle turnaround-buffered windows (adjacency rejected) — different semantics/resources
- **compensating_invariant**: bed-pool conservation (`beds_effective == occupied + reserved + free`) across reserve/cancel; meal-unit conservation across receive/serve

## §1.9 corner design
43 real instances + 10 `excluded_because` stubs across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, complexity_layers, consistency_model); every one of the 30 error IDs has at least one trigger test; SoD covered on all three segregated pairs (shift self-confirm, reporter≠resolver, activator≠approver); both OCC rules get stale-version tests using `${var}`-captured versions.

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 968 calls scanned, all conform to §1.5; all 14 FK relations reverse-reachable (fixed by renaming nested-route params to `{id}` to match the linter's sub-resource convention)
- All grounds references resolve; all `excluded_because` stubs cite real §1.8 instance names; instance names unique across both files (72 total); forbidden concurrency vocabulary absent; file-split constraint honored. Note: the pre-existing `worklog.md`/`workspace/` in the task directory were left untouched.

## Step 3: Copy Shared Files — 2026-08-14T12:36:44.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1727_warming_cooling_center_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T12:50:23.000Z

The PRD is generated and all three hard contracts pass. Summary below.

## Output

- **Path:** `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/workspace/PRD.md`
- **Line count:** 309 lines
- **Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Section inventory

- **§1 Introduction** — 2 paragraphs (business context + system scope; `/api` mount declared)
- **§2 Global Specifications** (9 subsections, domain-derived): 2.1 RBAC, 2.2 API Response Structure (verified byte-identical to the fixed verbatim block), 2.3 Pagination, 2.4 Logical Clock and Time Semantics, 2.5 Resource Identity/Timestamps/Versioning, 2.6 Capacity Pools and Bed Conservation, 2.7 Numeric Precision/Rounding/Threshold Inclusivity, 2.8 Optimistic Concurrency Control, 2.9 Validation Order and Error Precedence
- **§3 Business Logic & Workflows** (8 subsections, lifecycle-timeline grouping): 3.1 Weather Surveillance & Activation Trigger, 3.2 Site Registry/Designation/Opening Gates, 3.3 Roster/Shifts/Overnight Coverage, 3.4 Guest Registration & Stay Lifecycle, 3.5 Outreach Transport & Dispatch Reservations, 3.6 Donations/Meal Stock/Meal Services, 3.7 Incident Escalation & Guest Safety Holds, 3.8 Extensions/Deactivation/Ops Sweeps/After-Action Closure
- **§4 Endpoint Definitions** — 56-row table, 4 columns only (Method, Path, Description, Authorized Role)
- **§5 Error Code Catalogue** — 30-row table, 2 columns only (Error ID, HTTP Status)

## Zero-silence coverage audit (scaffold table → PRD section)

| Scaffold table | PRD home(s) |
|---|---|
| `response_envelope` (§1.0) | §2.2 (verbatim block), §2.3 (limit 10/1/100, offset 0, sort `created_at` ASC, meta fields; weather-reading `observed_at` sort exception noted in §2.3 and §3.1) |
| `entities` (§1.1, 14 entities) | Field defaults/constraints/pinning scattered through §2.5–2.7 and §3.1–3.8; WeatherReading append-only exception (no `updated_at`/`version`) explicit in §2.5 |
| `state_machines` (§1.2, 9 machines / 34 transitions) | Episode §3.1 + §3.8; SiteActivation §3.2; Shift §3.3 (+sweep completion §3.8); GuestStay §3.4 (+ejection §3.7, cascade/no-show §3.8); TransportDispatch §3.5 (+L3 cascade §3.8); Donation/MealService §3.6; Incident §3.7; AfterActionReport §3.8 |
| `concurrency_rules` (§1.2.1, 2 rules) | §2.8 (both write endpoints, OCC fields, `ERR_STALE_VERSION`/412, no race framing); extensions reiterated §3.8 |
| `calculations` (§1.3, 9 rules) | breach_run_evaluation §3.1 (inclusive thresholds, 15-minute gap tolerance with 15-keeps/16-breaks, exactly-equal qualifies, floor to minutes); capacity_recompute §2.6 (incl. conservation invariant); dispatch_reservation_capacity §3.5 (all-or-nothing, beds→pets→lockers order); overnight_coverage_gap §3.3 (22:00–06:00, 480 minutes, touching-endpoint merge, lead containment); bed_nights §3.4 (both variants, boundary inclusivity); supply_stock §3.6 (on-hand vs projected); meal_planned_rounding §3.6 (1.10/1.15/1.25 buffers, round-per-line, sum-then-round forbidden); aar_aggregation §3.8; ops_sweep §3.8 (3 pinned steps, 60-minute no-show grace) |
| `validations` (§1.4, 9 priorities) | §2.9 (full nine-tier precedence in prose); per-rule triggers paired with error IDs in §3.1–3.8 (incl. gap-before-lead ordering at open, pinned beds→pets→lockers order at intake/transfer/assign) |
| `endpoints` (§1.5, 56 endpoints) | §4 table (method/path/roles/status semantics); side effects in matching §3 narratives; all query/filter params named in §3 prose |
| `errors` (§1.6, 30 IDs) | §5 table; all 30 IDs verified present in §2/§3 narrative |
| `roles` (§1.7, 6 roles) | §2.1 with per-role `identity:` translations (EOCManager/TransportCoordinator opaque; the four entity-backed roles tied to `StaffMember` `id`) |

## Hard contract reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 102 required, 102 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 9 tiers expressed in §2.9 prose, 0 missing
- concurrency_rules[] OCC: 2/2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412), 0 missing
- state_machines transitions: 34/34 expressed with preconditions and side effects, 0 missing
- calculations: 9/9 in precise prose (no pseudocode, no fuzzy words; operator-leak scan clean), 0 missing
- validations conditions: 30/30 error IDs matchable in §2/§3, 0 missing
- endpoint side effects / applies_to: all expressed (medical-hold 3-endpoint scope, 4 open gates, L1–L3 cascade), 0 missing
- field structured content: all defaults/constraints reconstructible (incl. source=MANUAL, turnaround_minutes=30, transfer_sequence=0, severity 1–3, pet_count=0-when-has_pets-false), 0 missing
- sibling symmetry: WARMING/COOLING, MEDICAL/BEHAVIORAL (sev 3 eject vs sev 1–2 no-op), REQUESTED vs ASSIGNED cancel, OPENING vs DRAINING close, REPORTED vs ESCALATED resolve, provisional vs final, on-hand vs projected — all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 446
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 is byte-identical to the canonical verbatim block; no pseudocode operators (`==`, `>=`, `ceil(`, `AND`, …) anywhere in the document; no fuzzy/approximating words; PRD ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T13:37:13.000Z

Generation is complete and the audit is clean. Final summary:

## Summary — task_1727_warming_cooling_center_operations

### Files written

**`test_helpers/` (Stage 1)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/test_helpers/`:
- `types.py` — 12 status/field enums + 14 entity TypedDicts; `WeatherReading` correctly omits `updated_at`/`version` (append-only exemption)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (56 endpoints, all `/api`-prefixed)
- `api_errors.py` — `ApiErrorId` (30 errors) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (lenient on nullable/unpinned fields), `assert_bed_conservation` invariant, `parse_instant` helper
- `factories.py`, `constants.py` (MAX_GAP_MINUTES=15, NO_SHOW_GRACE=60, overnight window, meal buffers, BAGS_PER_LOCKER=2)
- `test_users.py` — shared constants for all 6 roles + per-instance `make_*_headers` builders (mandatory for the 4 entity-backed roles)
- `fixtures.py` — ~40 primitives + 25 composite scenes covering every non-trivial setup chain in both design indices (open-site workhorse, dispatch scenes, cascade/deactivation scenes, AAR lifecycles, double-cycle script, etc.), with identity threading for SoD-gated calls

**`test_suite/` (Stage 2)** — `conftest.py` + 10 concern-grouped files (`test_01_envelope_pagination_auth` … `test_10_incidents_and_after_action`).

### Coverage (self-audit verified programmatically)
- **81 tests total; every one carries exactly one terminal `Design:` line resolving to a real instance.**
- Queue A (Difficulty): **19/19 instances × 2 tests = 38 tests** — full depth coverage (dual variants, combinatorial formulas, both cyclic machines, depth-3 and depth-2 cascades, both priority pairs, all three boundary metrics, both cross-entity gates, both overlap geometries, both conservation invariants).
- Queue B (Corner): **43/43 non-stub instances × 1 test = 43 tests**.
- The 10 `excluded_because` stubs were NOT translated; all 10 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- Instances skipped for PRD-first reasons: **none** — every instance has verbatim PRD coverage with uniquely-derivable outcomes (this PRD is unusually precise: §2.9 explicitly pins the validation order that the priority-pair instances assert, and §3.2 pins gap-before-lead ordering).

### Two-reader relaxations applied (assertion drops, not skipped instances)
1. `Corner/entities/episode_create_applies_system_defaults`: asserts the five verbatim defaults (status/trigger_met/breach_run_minutes/extension_count/ops_run_index) but drops `version == 1` and null-stamp assertions — the PRD never states the initial version value nor that stamp fields render as null pre-mutation.
2. Timestamp value checks (`observed_at`, `scheduled_end_at`) compare parsed instants rather than exact strings — the PRD pins three-fractional-digit rendering only for `created_at`/`updated_at`.

### Audit results
- pytest collects all 81 tests cleanly; py_compile passes on all files
- No `skip`/`skipif`/`xfail` markers anywhere
- No scaffold references in comments/docstrings (PRD §-references only)
- All quoted docstring spans grep verbatim in PRD.md (3 audit warnings confirmed as false positives: sub-8-word quotes and a nested-quote artifact, each independently grep-verified)
- No unused imports in test files; barrel re-exports in `__init__.py` are intentional

## Step 6: Generate Implementation — 2026-08-14T13:37:13.000Z

Done. Complete implementation generated, smoke-tested, and verified to boot cleanly from a fresh process.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/workspace/implementation/`)

- `start.sh` (executable) — guarded pip install (`import flask` check), `exec python3 app.py` in foreground, `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask wiring, ApiError/404/405/500 handlers, blueprint registration under `/api`
- `db.py` — in-memory dicts per entity + global insertion sequence (stable created_at tie-break); **no seeding — store starts empty every boot**
- `clock.py` — logical clock, fixed startup default `2026-08-01T00:00:00Z`
- `errors.py` — full 30-entry error catalog with exact IDs/HTTP statuses
- `response.py` — envelope: `meta.{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error body `data.{error_id, message}`
- `auth.py` — `X-User-ID`/`X-User-Role` validation, six roles, per-endpoint role decorator
- `util.py` — ISO-8601 parse/render (3-fractional-digit `Z`), field validators, `limit`/`offset` pagination (default 10, 1–100), `touch()` version bump
- `services.py` — all calculations, cascades, sweep, serializers
- `routes/{episodes,sites,workforce,stays,transport,supplies,incidents,aar}.py`

## Endpoint count
56 endpoints implemented — the full scaffold table: 9 episode-lifecycle, 3 site, 5 site-activation, 7 staff/shift, 8 guest/stay, 8 vehicle/dispatch, 6 donation/meal, 5 incident, 4 AAR, 1 clock.

## Calculations / state machines
- **breach_run_evaluation**: chronological walk sorted `(observed_at, created_at, seq)`; non-breach resets; gap ≤ 15 (floored minutes) extends, > 15 restarts; inclusive thresholds (`COOLING: heat_index_f >= t`, `WARMING: temp_f <= t`); `trigger_met` when run ≥ `sustained_hours_required*60` (exactly-equal qualifies)
- **capacity pools**: live aggregation; `beds_effective` pinned at first open (override else site capacity, frozen against later PATCH); pet/locker pools read live site values; conservation invariant holds
- **overnight coverage**: tonight = `[today 22:00, tomorrow 06:00)` on the logical clock; half-open interval merge of CONFIRMED shifts only (touching merges); `lead_coverage_ok` = CONFIRMED SITE_LEAD shift fully containing the window
- **bed_nights**: `midnight_crossings(a,b) = (b.date() − a.date()).days`; final at checkout/eject/transfer, provisional = crossings to now + 1 while CHECKED_IN
- **meal stock / planning**: on_hand = RECEIVED MEAL − SERVED sums; projected adds PLEDGED; `planned_meals = ceil(attendance × Decimal buffer 1.10/1.15/1.25)` per service (round-per-line)
- **ops_sweep**: pinned order shifts→COMPLETED, no-show expiry at `arrived_at + 60m`, DEACTIVATING settle; `ops_run_index`/`version` +1 exactly once
- **deactivation cascade L1→L2→L3**: OPEN→DRAINING (created_at ASC) cancelling RESERVED stays, OPENING→CLOSED with shift cancellation, dispatch auto-CANCEL when its live `reserved_bed_count` hits 0 while ASSIGNED; re-surge DEACTIVATING→ACTIVE returns DRAINING→OPEN without resurrecting stays
- **State machines**: all 9 entities with terminal lockdowns; SoD on shift-confirm/incident-resolve/AAR-approve; kind-keyed incident roles (wrong kind → 403); MEDICAL hold computed live; BEHAVIORAL sev-3 ejection; AAR aggregates pinned at creation
- **Validation order** per PRD §2.9: 401 → 403 → 404 (path left-to-right, then body refs) → 412 OCC (`expected_episode_version`/`expected_site_version`) → state guards parents-first + payload 400 → safety (hold/skill) → constraints (SoD, overlap, conflicts, cross-episode) → temporal (422 windows, gap before lead) → capacity beds→pets→lockers

## Boot smoke-test result
- Fresh `bash start.sh` on `PORT=19901`: booted in ~2s; `GET /api/stays` → `200 {"data":[],"meta":{...,"total_count":0},"response_type":"array"}` (empty store confirmed); `POST /api/sites` → 201 with correct envelope and logical-clock timestamps; killed cleanly. Two full scenario suites (~75 assertions) passed: trigger cycles/stand-down/re-surge, OCC 412s, coverage-gated open, intake pools, dispatch assign/arrive/no-show, L3 cascade cancel, transfers (incl. cross-episode 409 to an OPEN foreign site), behavioral ejection, medical hold gating, donations/stock/serving, AAR draft→submit→approve→episode CLOSED, and pagination validation. (Three apparent failures during testing were bugs in my throwaway test scripts, not the server.)

One note: another task's `prd-bench-local-run` sweep (task_1730) is running concurrently on this host spawning its own `app.py` processes — I scoped all cleanup to processes whose cwd is the task_1727 implementation directory.

## Step 7: Test-and-Fix Iteration Loop — 2026-08-14T14:05:00Z

First 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30`, 8 concurrent rounds) completed clean on the first iteration — no fixes were needed.

- Iterations run: **1**
- Round results: **81/81 passed in every one of rounds 1-8** (648 test executions total, 0 failures, 0 flakes)
- Union of failing tests across rounds: **empty**
- Tests deleted: none
- Fixes applied to `test_helpers/`: none
- Fixes applied to `test_suite/`: none
- Fixes applied to `implementation/`: none

Result files: `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-08-14T13:42:36.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline, so `PRD.md` already determines every behavior the implementation exhibits. No `PRD_FINALIZED.md` was produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T14:05:51.000Z

All verified. The task is complete — `PRD_COMPLETED.md` is written with 23 in-paragraph edits, all pinned to the implementation.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1727_warming_cooling_center_operations/workspace/PRD_COMPLETED.md`
**Size**: PRD.md 308 lines / 46,313 chars → PRD_COMPLETED.md 308 lines / 49,044 chars (char-delta **+2,731**; every change is an in-paragraph insert/revision — no new paragraphs, no new sections, line count unchanged).
**Counts**: **19 ambiguity-pins** (insert), **5 mismatch-revisions** (revise) across 23 hunks (one hunk carries one of each).

### Mismatch-revisions (PRD described a different behavior than impl)

- **§2.9** — revise — mismatch — moved the incident kind-role `ERR_FORBIDDEN` check out of the tier-2 authorization group: impl applies it only after the incident's existence is established (a nonexistent incident yields `ERR_NOT_FOUND` regardless of role-kind match) and before the incident state guard — `implementation/routes/incidents.py:110-111,133-134`
- **§3.2** — revise — mismatch — opening gates reordered to impl's actual five-check order: episode `ACTIVE` → activation still `OPENING` (`ERR_INVALID_STATE`) → pinned bed capacity ≥ 1 (`ERR_VALIDATION`) → `ERR_OVERNIGHT_COVERAGE_GAP` → `ERR_LEAD_COVERAGE_MISSING` (PRD had "four checks" with the bed-capacity check last) — `implementation/routes/sites.py:178-206`
- **§3.3** — revise — mismatch — confirmation's four checks reordered to impl order: staff active (`ERR_INVALID_STATE`) → skill (`ERR_SKILL_MISMATCH`) → self-confirmation segregation (`ERR_SEGREGATION_OF_DUTIES`) → overlap (`ERR_SHIFT_OVERLAP`); PRD listed segregation first — `implementation/routes/workforce.py:168-191`
- **§3.4** — revise — mismatch — transfer check order revised to impl: source stay `CHECKED_IN` (`ERR_INVALID_STATE`) → target `OPEN` (`ERR_SITE_NOT_OPEN`) → medical hold → same-episode (`ERR_CROSS_EPISODE_TRANSFER`) → capacity; PRD listed cross-episode first — `implementation/routes/stays.py:212-242`
- **§3.5** — revise — mismatch — assignment check order revised to impl: destination `OPEN` (`ERR_SITE_NOT_OPEN`) → dispatch still `REQUESTED` (`ERR_INVALID_STATE`) → no rider with active stay → vehicle window conflict (only against dispatches still `ASSIGNED`) → seats ≥ riders (`ERR_VEHICLE_TOO_SMALL`) → capacity; PRD listed seats/window first — `implementation/routes/transport.py:164-213`

### Ambiguity-pins (PRD silent; pinned to impl)

- **§2.2** — insert — ambiguity — `api_request_timestamp` is generated from the wall clock, not the §2.4 logical clock — `implementation/response.py:15-17`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit` (outside 1–100) or non-integer/negative `offset` rejected with `ERR_VALIDATION`; `has_more` true exactly when `offset` + returned page size < `total_count`; ordering ties (identical `created_at` under the frozen logical clock) break by insertion order — `implementation/util.py:143-166`, `implementation/db.py:29-32`
- **§2.5** — insert — ambiguity — `version` starts at 1 at creation — `implementation/routes/episodes.py:61` (same in every create handler)
- **§2.6** — insert — ambiguity — `beds_effective` and `beds_free` are null until the first successful open pins the value — `implementation/services.py:117-120`
- **§2.8** — insert — ambiguity — the OCC version field is itself validated for presence and integer type (`ERR_VALIDATION`) before the staleness comparison, and both run before state guards and remaining payload checks — `implementation/routes/episodes.py:170-180`, `implementation/routes/sites.py:80-90`
- **§3.1** — insert — ambiguity — weather readings may be appended in any episode state; the breach recompute (on append or on episode read) never advances the episode's `version`/`updated_at` — `implementation/routes/episodes.py:73-98`, `implementation/services.py:74-76`
- **§3.1** — insert — ambiguity — a `DEACTIVATING`→`ACTIVE` re-surge keeps the prior `deactivated_at` stamp (never cleared) — `implementation/services.py:305-317`
- **§3.2** — insert — ambiguity — a PATCH that passes the OCC guard advances `version`/`updated_at` even when no supplied field changes a value — `implementation/routes/sites.py:106`
- **§3.3** — insert — ambiguity — roster `active` filter accepts only case-insensitive `true`/`false`, anything else yields `ERR_VALIDATION` — `implementation/routes/workforce.py:67-73`
- **§3.3** — insert — ambiguity — shift confirmation additionally requires the shift's activation in `OPENING`/`OPEN` and the shift in `PLANNED`, else `ERR_INVALID_STATE` — `implementation/routes/workforce.py:155-164`
- **§3.4** — insert — ambiguity — `has_pets` true with `pet_count` zero is permitted (only the false⇒zero direction is enforced) — `implementation/routes/stays.py:49-50`
- **§3.4** — insert — ambiguity — transfer response carries the newly created successor stay — `implementation/routes/stays.py:264`
- **§3.4** — insert — ambiguity — a stay that never reached check-in reports `bed_nights_provisional` zero — `implementation/services.py:203-206`
- **§3.5** — insert — ambiguity — rider count is the length of the `guest_ids` array — `implementation/routes/transport.py:177`
- **§3.5** — insert — ambiguity — cancelling an `ASSIGNED` dispatch ends the vehicle's window occupation just as arrival does (window-conflict check only considers `ASSIGNED` dispatches) — `implementation/routes/transport.py:185-188,263-268`
- **§3.6** — insert — ambiguity — donations and meal services are recorded/received/planned/served regardless of activation status; no state gate exists on these endpoints — `implementation/routes/supplies.py:43-162`
- **§3.6** — insert — ambiguity — `service_date` is stored and returned exactly as supplied (normalized to UTC); its time component carries no meaning rather than being discarded — `implementation/routes/supplies.py:105`, `implementation/services.py:544`
- **§3.7** — insert — ambiguity — incident reporting, escalation and resolution are not gated on the activation's or episode's status — `implementation/routes/incidents.py:39-77,107-151`
- **§3.8** — insert — ambiguity — the ops sweep may be run in any episode state — `implementation/routes/episodes.py:213-218`
- **§3.8** — insert — ambiguity — a stay whose `bed_nights_final` is still null contributes zero to the after-action `total_bed_nights` — `implementation/routes/aar.py:69`

**Notable verifications with no change needed**: all 45 endpoint table rows map 1:1 to implemented routes with matching roles; the §2.9 nine-tier precedence matches every endpoint's actual check order (OCC before state guards on both guarded endpoints; beds→pets→lockers capacity order everywhere; medical-hold safety gate before uniqueness); breach-run 15-minute gap rule, inclusive thresholds, per-service ceiling meal rounding, midnight-crossing bed-night formulas, deactivation L1/L2/L3 cascade, no-show 60-minute grace, and the settle-on-last-close shortcut all match impl exactly. Unreachable edges (e.g., settling a zero-activation episode, approving while `DEACTIVATING`) were deliberately left unpinned since they cannot arise through the API.
