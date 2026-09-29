# Worklog — task_2513_player_tracking_sports_data_operations

## Step 1: Create task directory — 2026-09-03T03:36:00.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations` and its `workspace/` subdirectory. Index 2513 was fixed by the invoking scenario number; no scan of `./tasks/` for a highest index was performed (other pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate Scaffold — 2026-09-03T05:08:00.000Z

All three scaffold artifacts for scenario 2513 are complete and lint-clean, generated purely from the scenario text plus the scaffold-generator spec (no sibling task was read, listed, or grepped at any point).

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/`)
- `SCAFFOLD.yaml` — 2557 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1653 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4071 lines, single key `scaffold_corner_design`

**Scaffold counts** — difficulty `expert_plus`; archetypes compliance_audit / quota_allocation; 14 entities (2 immutable: CalibrationRun, LicenseUsageRecord); 7 state machines (Game carries two independent dimensions — `collection_status` × `certification_status`); 1 concurrency rule (`event-tag-create-stale-game`, `expected_game_version` → ERR_STALE_GAME_VERSION/412); 6 calculations, 2 of them dual-variant (`feed_session_billing`: RESERVED_FORWARD vs METERED_ACTUAL; `normalized_tracking_metric`: RAW_GENERATION round-then-sum vs CANONICAL_SEASON sum-then-round); 40 validation rules across priorities 1–82; 50 endpoints (incl. the `POST /_clock/set_current_utc` driver that reports `expired_consent_record_count` / `suspended_feed_session_count`); 54 errors; 6 roles (4 opaque + 2 entity-backed: ClubDataOfficer→Club, Licensee→DataLicensee) under a segregation-of-duties model.

**Design instances** — §1.8: 18 instances (2 per each of the 9 required rule_ids). §1.9: 65 instances across 9 sections — entities 10, state_machines 15, calculations 10, validations 14, endpoints 4, errors 2, rbac 5, complexity_layers 4, consistency_model 1 — of which 9 are `excluded_because` stubs that defer to a named §1.8 instance, leaving 56 active recipes. Lint: `VERDICT: clean lint`, 828 calls scanned, all §1.1 FKs reverse-reachable. Every one of the 54 error ids is triggered by at least one design instance; all 83 instance names are unique across the two files.

**Adjudications made**
- *Certification vs. archival deadlock*: certifying a game archives it, so the priority-42 "COLLECTED" gate made ERR_GAME_ALREADY_OFFICIAL (44) and the whole DISPUTED→PROVISIONAL→OFFICIAL re-certification cycle unreachable. Priority 42 now accepts `{COLLECTED, ARCHIVED}` on certify (rationale written into the check text), with the Game transition precondition and side effect reworded to match.
- *Three separate authorities over one scope array*: paperwork (53, `biometric_entitled`) precedes tier (62, `TIER_ALLOWED_SCOPES`) precedes window (63, `allowed_scopes`). Proved with a GOLD-but-unentitled licensee and a SILVER-but-entitled licensee so no rung can be confused for another.
- *Accuracy before state*: priority 39 (`latest_run_result == PASS`) deliberately precedes 40 (installation from-set), so a never-calibrated DEPLOYED rig answers ERR_CALIBRATION_NOT_PASSING rather than a state error.
- *Two disjoint allocation pools*: LEAGUE_ARCHIVE draws only on the 15% reserve (36 min of 240) and can be exhausted while 204 net minutes sit free; the reserve is computed on gross licensable minutes, never on the net pool it creates.
- *Computed-field corners must assert 400*: priority 15's "no unknown fields" rule means a client-supplied computed value is rejected, not silently ignored — the relevant instance is named with the `_input_ignored` marker so the linter skips its payload check.
- *Supersession corners use the declared DRAFT→SUPERSEDED row* rather than SUBMITTED→SUPERSEDED, so every replayed call matches a declared `from:` state.
- Verified boundary literals used throughout: calibration 90.00 PASS / 140.00 PROVISIONAL / 140.01 FAIL, 72h valid vs 73h expired; quality_index 0.8000 admitted at the floor, 0.7250 after a rejected correction; billing 900 units @250 ms (19800c GOLD), 720 @300 ms, 300 @2000 ms; reservation ceiling inclusive at 900 (915 refused); SLA credit 165c per breach, suspension at the 3rd breach with 495c credited; G1 normalization 125.56, G2 canonical 264.29.

Two incidental fixes: 16 endpoint `input:` flow sequences had bare `?` members that broke YAML parsing (now quoted, e.g. `["status?", "limit?", "offset?"]`), and the `"CBA-2026A"` literal was added to validation priority 52 and the ERR_CBA_VERSION_MISMATCH condition.

Orchestrator verification: all three files parse as YAML; top-level keys confirmed correct (SCAFFOLD.yaml has neither design key; the two design files each carry exactly their single key).

## Step 3: Copy shared files — 2026-09-03T05:09:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T05:21:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/workspace/PRD.md` — 444 lines, ~13,400 words, written in six sequential passes (Write for the first block, then append-edits, then a scripted append for the two tables).

**Sections written**
- §1 Introduction (3 paragraphs: regulated-asset framing, system scope, the two governing commitments)
- §2 Global Specifications — 11 subsections, domain-derived titles: 2.1 RBAC, 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity and Audit Fields, 2.5 Path Resolution and Reverse-Lookup Channels, 2.6 The Logical Clock, 2.7 Numeric Precision / Rounding / Ceiling Discipline, 2.8 OCC on the Game Aggregate, 2.9 Segregation of Duties, 2.10 Rejection Precedence (all 44 checks as a fixed-order ladder), 2.11 Cascade Discipline and Census Invariants
- §3 Business Logic — 9 subsections grouped by subsystem lifecycle: venues/installation census, calibration & rig certification, clubs/rosters/consent chain, game scheduling & the two collection dimensions, event tagging & quality review, corrections/quality index/game certification, rights allocation, licensees & feed sessions & the unit ledger, historical normalization
- §4 Endpoint Definitions (4 columns), §5 Error Code Catalogue (2 columns)

**Coverage / truncation verification (scripted against SCAFFOLD.yaml)**

Note the actual scaffold surface differs slightly from the numbers in the brief: **44 validation rules** (not 40) and **53 error codes** (not 54). All other counts matched.

```
Field coverage check:
- entities[].fields: 140 required, 140 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose (ordered ladder in §2.10 + business narrative in §3), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (tag-create write endpoint + expected_game_version + ERR_STALE_GAME_VERSION + 412), 0 missing
- state_machines[].transitions: 7 machines / 31 transitions checked, 31 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed incl. all constants and both variant pairs (RESERVED_FORWARD/METERED_ACTUAL, RAW_GENERATION/CANONICAL_SEASON), 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 50 endpoints checked, all side effects and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked (incl. common_fields:false on CalibrationRun and LicenseUsageRecord stated explicitly), reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (approve/reject correction, DISPUTED→PROVISIONAL vs DISPUTED→OFFICIAL, flag-drift/retire cascade, withdraw/expire consent cascade, two billing variants, two normalization bases), 0 asymmetric
- all 53 error ids appear in §2/§3 prose in addition to the §5 table; all 6 roles named with identity translated; all state enum values present verbatim
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 862
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Truncation check:** §4 table has exactly 50 rows × 4 columns; §5 table has exactly 53 rows × 2 columns; the file's last line is a complete table row (`` | `ERR_SESSION_RESERVATION_EXCEEDED` | 402 | ``) followed by a newline — a genuine section boundary, no mid-sentence or mid-table cut. All 25 expected headings (§1, §2 + 11 subsections, §3 + 9 subsections, §4, §5) are present. No fuzzy/approximating quantifiers and no pseudocode operators (`==`, `>=`, `+=`, `ceil(`, `round_half_up`, `sqrt`, `IN {`) appear anywhere in §1–§3.

Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator anti-truncation re-verification (independent of the subagent):** `wc -l` = 444; `tail -25` shows the file ending on the complete final row of the §5 table; `grep '^#'` confirms all 25 headings in order through `## 5. Error Code Catalogue`. PRD accepted, no regeneration needed. The difficulty instruction ("Generate task harder than expert level!") was passed only to the Step 2 scaffold subagent and does not appear in PRD.md.

## Step 6: Generate Implementation — 2026-09-03T05:52:00.000Z

Implementation complete and verified. All test servers are shut down and `__pycache__` is cleaned up.

## Files written

Root: `/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 73 | Flask factory, blueprint registration, global request lock, error handlers |
| `start.sh` | 10 | Launcher: guarded pip install, `exec python3 app.py`, honours `$PORT` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `db.py` | 152 | In-memory store (14 dicts), audit stamps, `version` bump, query helpers |
| `errors.py` | 83 | All 54 error ids → HTTP status, `ApiError` |
| `response.py` | 63 | `meta`/`response_type`/`data` envelopes, `req_` + 20 uppercase alnum |
| `auth.py` | 43 | `X-User-ID`/`X-User-Role` → 401 then 403 |
| `validation.py` | 199 | Rank-4 body schema + pagination/filter params |
| `util.py` | 137 | ISO stamps, `Fraction` arithmetic, `round_half_up`, ceiling, ordering |
| `calc.py` | 222 | Domain constants + all 6 PRD calculations |
| `lookups.py` | 74 | Per-entity 404 resolvers |
| `services/venue.py` | 79 | Installation census, venue posture, degradation cascade |
| `services/quality.py` | 35 | Tag census moves, quality index recompute |
| `services/consent.py` | 88 | Consent-loss cascade, clock-driven expiry sweep |
| `services/rights.py` | 66 | Minute ledger recompute, territory/window collision |
| `services/billing.py` | 60 | Settlement, refund, unit-ledger conservation |
| `routes/venues.py` | 282 | 10 endpoints |
| `routes/clubs.py` | 242 | 9 endpoints |
| `routes/games.py` | 305 | 9 endpoints |
| `routes/tags.py` | 389 | 9 endpoints |
| `routes/rights.py` | 165 | 3 endpoints |
| `routes/feeds.py` | 406 | 9 endpoints |
| `routes/clock.py` | 42 | 1 endpoint |
| `routes/__init__.py`, `services/__init__.py` | 0, 0 | packages |

**3216 lines total, 24 files.**

## Endpoint coverage

**50 / 50** — the Werkzeug URL map yields exactly 50 method+rule pairs (`static_folder=None` suppresses Flask's implicit `/static` rule), matching the 50 rows of PRD §4 one-for-one.

## Storage

In-memory dicts only. A grep for `sqlite`, `open(`, `json.dump`, `pickle`, and `/tmp` across the implementation returns nothing. Every collection is empty at boot; no entity is seeded. Only `store.clock` has a non-empty startup value, the PRD-mandated `2026-08-01T00:00:00Z`.

## Boot check

`PORT=17516 bash start.sh` booted from a fresh process and served **25/25** envelope and rejection assertions: object and array envelopes with exactly the PRD `meta` key sets (`api_request_id`, `api_request_timestamp`, plus `limit`/`offset`/`total_count`/`has_more` on arrays), `req_`+20-char id shape, 401 before 403, rank-4 rejections (missing field, bad enum, unknown field, `limit=0`/`limit=101`/`offset=-1`), body-FK 404, unknown path 404, 405 on a bad method, and a `version: 1` audit complement on a created row.

A second fresh boot on port 17513 then passed the full **30-step end-to-end** flow with exact arithmetic verified against hand calculations: venue→rig→calibration PASS→auto-VALIDATED→certify→`CERTIFIED` posture; consent file+ratify→`GRANTED`; game ledger 15 reserve / 85 net; tag create + `412 ERR_STALE_GAME_VERSION` + submit/accept→quality_index 0.8→`PROVISIONAL`; 60-minute rights window leaving 25 allocatable; session reserved 450 units / 9900 cents; breach usage record with `sla_credit_cents` 825; terminate metered 150 / settled 3300 / refunded 300 with the unit ledger conserved at 100000; both normalization bases plus `422 ERR_NORMALIZATION_SEGMENTS_EMPTY`; certify game→`OFFICIAL`; flag-drift→venue back to `UNCERTIFIED`; clock advance→consent `EXPIRED` with 1 tag masked.

## One bug found and fixed during this verification

`validation.py::raw_body` used `request.data` as its empty-body guard. In Werkzeug `Request.data` is `get_data(parse_form_data=True)`, so a JSON body sent *without* a `Content-Type: application/json` header (urllib's default is `x-www-form-urlencoded`) was handed to the form parser and reported as empty — turning a valid create into `400 ERR_INVALID_REQUEST`. Now:

```python
if not request.get_data(cache=True, parse_form_data=False):
    return {}
body = request.get_json(silent=True, force=True)
```

`requests`-based clients that set the header were never affected, but header-less clients now work too. `python3 -m compileall -q .` passes clean.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it.

## Step 5: Generate Unit Tests — 2026-09-03T06:53:00.000Z

Test infrastructure and test suite are complete for `task_2513_player_tracking_sports_data_operations`.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/test_helpers/` (9 files)
`__init__.py`, `types.py`, `constants.py`, `api_errors.py`, `test_users.py`, `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`

`/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/test_suite/` (19 files)
`conftest.py` (fixtures `api`, `clock`) plus `test_01_feed_session_billing.py`, `test_02_feed_session_admission.py`, `test_03_normalization.py`, `test_04_rights_allocation.py`, `test_05_game_lifecycle.py`, `test_06_installation_lifecycle.py`, `test_07_cascades.py`, `test_08_event_tags.py`, `test_10_entities.py`, `test_11_state_machines.py`, `test_12_calculations.py`, `test_13_validations.py`, `test_14_endpoints.py`, `test_15_errors.py`, `test_16_rbac.py`, `test_17_complexity_layers.py`, `test_18_consistency.py`.

## Test counts per queue

- **106 test functions**, 109 collected (one 4-case `parametrize` in `test_06`). `PYTHONPATH=. pytest test_suite -q --collect-only` → "109 tests collected".
- **Queue A (Difficulty, §1.8): 52 tests** across all **18** non-stub difficulty instances, minimum 2 tests per instance.
- **Queue B (Corner, §1.9): 54 tests** across **54** corner instances, exactly one test each.
- Every test carries exactly one `Design:` line as its last docstring line; 0 unknown tags, 0 dual tags, 0 stub instances translated.
- The corner index's 65 non-stub entries include 9 that carry an `excluded_because.difficulty_instance` cross-reference (deliberately deferred to queue A), leaving 56 test-bearing instances: 54 covered, 2 skipped.

## PRD-citation pass

Every docstring now opens with verbatim `PRD §X: "<full sentence>"` citations — 245 citations total. Each was machine-extracted from `workspace/PRD.md` and re-verified: all 245 are literal substrings of the PRD after whitespace normalization, with section labels derived from the nearest preceding heading. Seven citations are complete PRD sentences shorter than 8 words (e.g. §3.7 "Revoked windows contribute nothing to either total."); each of those seven tests also carries a 14–55-word verbatim citation, so the ≥8-word grep check holds per test.

Hygiene: all files compile; no `skip`/`xfail`/mock/`monkeypatch`; zero case-insensitive "scaffold" matches in either directory. Nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched — the suite was written blind.

## Skipped design instances (2)

1. **`Corner/validations/correction_proposed_player_must_be_on_one_of_the_two_rosters`** — the instance asserts `ERR_PLAYER_NOT_IN_GAME` when the correction *is created*. PRD §2.10 rank 40 scopes the roster check to "creating an event tag and to approving a correction that proposes a replacement player", and §3.6 puts the eligibility test on **approval**. Under the PRD the creation must succeed with 201, so the asserted outcome is contradicted, not merely unsupported.
2. **`Corner/rbac/licensee_cannot_read_another_licensees_session_or_ledger`** — asserts 403 `ERR_NOT_RESOURCE_OWNER` for licensee B on `GET /feed-sessions/{A's session}` and `GET /licensees/{A}`. PRD §2.10 rank 6 enumerates the ownership check's scope as filing/withdrawing a consent record, opening a correction as `ClubDataOfficer`, reporting a usage record, and terminating a feed session — neither read appears — and §4 lists `Licensee` as an authorized role on both reads with no ownership qualifier. Not uniquely derivable.

Both gaps were left as gaps: no weakened assertion, no `skip`/`xfail` marker, no placeholder.

## Step 7: Run Tests and Iterate — 2026-09-03T07:15:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (two full 8-round parallel sweeps).

**Tests deleted:** none. No test failed STEP 1 (PRD coverage / unique derivability) — the single failure was a fixture-arithmetic bug, not a PRD-silence issue.

**Fixes applied to `test_helpers/`:** none. The offending setup lived inline in the test module, not in the shared helpers.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2513_player_tracking_sports_data_operations/test_suite/test_14_endpoints.py`, helper `_biometric_session_world()` — changed the rights-window override `window_end_utc` from `2026-08-01T23:00:00Z` to `2026-08-01T21:00:00Z`. The window started at 18:00, so the override asked for a 300-minute allocation against a game whose net pool is only 204 minutes (`licensable_minutes=240` from `factories.game_payload`; PRD §3.7 gives `league_reserve_minutes = ceil(0.15 × 240) = 36`, `net_allocatable_minutes = 240 − 36 = 204`). The implementation correctly returned `409 ERR_ALLOCATION_POOL_EXHAUSTED` per §2.10 rank 42, aborting setup for `test_advancing_the_clock_reports_the_expiry_and_suspension_census`. The new 180-minute window fits the pool and still fully contains the session's half-open 18:00–18:30 occupation interval (§3.8 containment), so every assertion the test makes — `reserved_units == 720`, the `CONSENT_EXPIRED` suspension, the untouched ledger at available=4280/reserved=720 — is unchanged.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful throughout; no check was weakened or removed.

**Final sweep evidence** (`workspace/implementation/results.1..8.json`):

| round | passed/total |
| --- | --- |
| 1 | 109/109 |
| 2 | 109/109 |
| 3 | 109/109 |
| 4 | 109/109 |
| 5 | 109/109 |
| 6 | 109/109 |
| 7 | 109/109 |
| 8 | 109/109 |

No flakiness surfaced: the failure in iteration 1 was deterministic across all 8 rounds, and iteration 2 was green across all 8. Sweeps ran detached under `setsid nohup`, so no round was reaped mid-request.

**Orchestrator independent verification of sweep artifacts** (guarding against the known failure mode where a Step 7 subagent reports a clean sweep with no results files on disk): all eight `workspace/implementation/results.{1..8}.json` exist, parse as JSON, and each reports `passed=109 total=109 failed=0`. Confirmed directly by the orchestrator, not taken on the subagent's word.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 1 `test_suite/` fix, so the skip condition (0 deletions / 0 test_suite fixes / 0 test_helpers fixes / 0 implementation fixes) does not hold. Step 8 proceeds with the Step 7 entry inlined as `<step_7_diff>`. Note for the record: the single fix was a pure fixture-arithmetic bug with 0 implementation fixes, so Step 8 may legitimately find little or nothing to patch — that is an expected outcome, not a failure.

## Step 8: Finalize PRD — 2026-09-03T07:24:00.000Z

Investigation complete. The single `<step_7_diff>` item is a pure fixture-arithmetic bug with no underlying PRD silence or mismatch, so **`PRD_FINALIZED.md` is byte-identical to `PRD.md` with zero edits** (both 444 lines, 0.0% delta, md5 `b6d339b48aafc3f31287a82fb6301d09` for both). The file has been created.

**Line counts:** PRD.md 444 / PRD_FINALIZED.md 444 — 0 lines changed, 0.0% delta.

**Changes:** none.

**Why no edit was warranted** — every behavior the fixture fix depended on is already uniquely determined by PRD.md, and the implementation matches it verbatim:

- Reserve on the gross basis, ceilinged: PRD.md line 286 — "the league's archival reserve, `league_reserve_minutes`, is fifteen percent of the game's `licensable_minutes`, rounded up to a whole minute. The reserve is always a share of the *gross* licensable figure." Impl: `implementation/calc.py:154-156` (`ceil_units(F(licensable_minutes) * LEAGUE_RESERVE_PCT)`, `LEAGUE_RESERVE_PCT = Fraction(15, 100)` at `calc.py:28`). 240 → 36.
- Net pool: PRD.md line 286 step two, and the seeding at line 234. Impl: `implementation/services/rights.py:14-19` plus game creation. 240 − 36 = 204.
- Per-window draw: PRD.md line 286 — "the number of seconds between its `window_start_utc` and `window_end_utc` divided by sixty and rounded up… once per window and… never applied to a sum" (reinforced at line 108). Impl: `calc.py:159-162`. 18:00→23:00 = 300 minutes.
- Admission test and the refusal: PRD.md line 288 (pool-specific, equality admitted, `ERR_ALLOCATION_POOL_EXHAUSTED`), rank 42 at line 171, HTTP 409 at line 442. Impl: `implementation/routes/rights.py:82-92`, status map at `errors.py:58`.

So `300 > 204 → 409` is the only PRD-legal outcome; the test's `window_end_utc="2026-08-01T23:00:00Z"` override was simply an illegal request that aborted setup. Notably the fix restored the value already used by `test_helpers/factories.py:231` (default `window_end_utc` = `2026-08-01T21:00:00Z`, 180 ≤ 204) — i.e. the override was gratuitous, and removing it changes no observable implementation behavior. The session's 18:00–18:30 occupation (`factories.py:288-289`) remains strictly inside the 18:00–21:00 window under any reading of §3.8 containment, so the fix did not lean on the half-open detail either.

**Per-edit pre-edit search log:** not applicable — no edits were committed. For completeness, the subject investigated was the game minute ledger / rights-window allocation admission; the impl paths enumerated and read were `calc.py:28`, `calc.py:150-162`, `routes/rights.py:55-109` (full create-window rank chain), `services/rights.py:14-19` (ledger recompute), `errors.py:58`, plus a repo-wide grep for `POOL_EXHAUSTED`, `league_reserve`, `net_allocatable`, and `allocated_minutes` across `implementation/`. All were consistent with the existing PRD prose, so no wording adjustment was needed and no edit was made.

**Orchestrator note:** a zero-edit Step 8 is the expected outcome here, not a generator failure — Step 7 applied 0 implementation fixes and 0 deletions, so there was no impl-pinned choice for Step 8 to write down. The residual PRD-vs-implementation surface is Step 9's responsibility, and Step 9 always runs.

## Step 9: Complete PRD — 2026-09-03T08:00:00.000Z

Step 9 was deliberately run as **three sequential file-partitioned passes** rather than one subagent, because the implementation is 3216 lines across 24 files and a single-context exhaustive walk reliably degrades into a spot check (the known failure signature being a `PRD_COMPLETED.md` byte-identical to its input). Each pass edited `workspace/PRD_COMPLETED.md` in place; passes were run strictly sequentially so no two agents wrote the file concurrently. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from re-running it and from reverting earlier passes' edits.

**Partitioning:**
- Pass 1 — cross-cutting/global layer: `app.py`, `response.py`, `auth.py`, `validation.py`, `util.py`, `db.py`, `errors.py`, `lookups.py`, `routes/clock.py` (866 lines) → PRD §2.x
- Pass 2 — venue/calibration/club/consent: `routes/venues.py`, `routes/clubs.py`, `services/venue.py`, `services/consent.py`, calibration/posture portions of `calc.py` → PRD §3.1–§3.3
- Pass 3 — game/tagging/rights/feed: `routes/games.py`, `routes/tags.py`, `routes/rights.py`, `routes/feeds.py`, `services/quality.py`, `services/rights.py`, `services/billing.py`, billing/normalization/QI/SLA/ledger portions of `calc.py` → PRD §3.4–§3.9

**Aggregate counts across the three passes:** ~395 behaviors examined; **43 ambiguity-pins**; **11 mismatch-revisions**; ~341 behaviors verified already uniquely pinned. Total 54 edits, all in-paragraph — no new sections, no renumbering, no §4/§5 table rows added or removed.

### Pass 1 (global layer) — 13 pins, 4 mismatches
- §2.1 — revise — ambiguity — an empty header value counts as absent; role spelling matched exactly/case-sensitively — `auth.py:32`
- §2.1 — revise — **mismatch** — PRD said opaque `X-User-ID`s are compared "only for the segregation-of-duties checks"; impl also uses one for the tag-submission ownership check — `routes/tags.py:162`
- §2.1 — insert — ambiguity — the two enumerated club-ownership checks are the only ones; registering a player is not ownership-checked — `routes/clubs.py:68-86`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric characters — `response.py:21`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall clock, not the logical clock — `response.py:27`, `util.py:30`
- §2.2 — insert — ambiguity — unmatched path → 404, undeclared method → 405, both `ERR_INVALID_REQUEST`; trailing slashes tolerated — `app.py:52-58`, `app.py:28`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected, empty value falls back to default, over-range offset yields an empty page, undeclared query params ignored, query validation at rank 4 — `validation.py:147-175`
- §2.3 — revise — **mismatch** — two ordering exceptions, not one; session usage records order by client-supplied `sampled_at_utc` ASC (then `created_at`, then insertion order); licensee audit trail stays `created_at` ASC; calibration history `created_at` DESC — `services/billing.py:9-15`, `routes/feeds.py:384`, `routes/venues.py:208`, `util.py:131-137`
- §2.3 — insert — ambiguity — out-of-enum filter matches no rows (not a schema error), empty filter treated as absent, `sla_breach` accepts `true/false/1/0` any case — `validation.py:178-194`
- §2.4 — insert — ambiguity — `id` is a canonical lower-case hyphenated UUIDv4 — `db.py:60-62`
- §2.4 — revise — **mismatch** + ambiguity — `created_at`/`updated_at` are real wall clock; a venue-census re-derivation that moves no count and no posture is not a mutation, so it bumps neither `updated_at` nor `version` — `db.py:65-88`, `services/venue.py:39-42`
- §2.5 — insert — ambiguity — identifiers never shape-checked: a non-UUID string fails resolution with the matching 404, never `ERR_INVALID_REQUEST` — `lookups.py:25-29`
- §2.6 — insert — ambiguity — domain "now" stamps store the clock string verbatim; pre-set it reads `2026-08-01T00:00:00Z` — `db.py:16-48`, `routes/clock.py:31`
- §2.6 — insert — ambiguity — `to_iso8601` is the sole required field; the instant is adopted unconditionally, so the clock may move backwards or restate itself — `routes/clock.py:15-31`
- §2.6 — insert — ambiguity — clock response is a 200 object envelope with exactly three census keys, `current_utc` echoing the supplied spelling; lapse sweep runs on every set regardless of direction — `routes/clock.py:35-42`
- §2.7 — insert — ambiguity — ceilings computed in exact rational arithmetic, so a mathematically whole quantity ceilings to itself — `util.py:56-69`
- §2.10 rank 4 — revise — ambiguity — applies also to acting operations declaring no input; explicit JSON `null` treated as an omitted field — `validation.py:64-72,126-133`
- §2.10 rank 6 — revise — **mismatch** + ambiguity — added submitting an event tag to the rank-6 list; pinned that no read endpoint carries an ownership check — `routes/tags.py:162`, `routes/feeds.py:78-82`

### Pass 2 (venue/club/consent) — 17 pins, 5 mismatches
- §3.1 — insert — `required_certified_installations`/`min_achievable_latency_ms` whole numbers, `transport_capacity_mbps` may be fractional — `routes/venues.py:27-29`
- §3.1 — insert — `rig_label` uniqueness never tested; duplicates accepted — `routes/venues.py:32-36,105`
- §3.1 — insert — unfiltered installation list carries every status, `RETIRED` included — `routes/venues.py:88-91`
- §3.2 — insert — an `INVALID` verdict still computes/stores/mirrors `composite_rms_mm` — `calc.py:93-104`
- §3.2 — insert — a `PASS` run bumps rig `version` twice (CALIBRATING then VALIDATED), a non-passing run once — `routes/venues.py:167-177`
- §3.2 — insert — recording a run re-derives census/posture only, never fires the degradation cascade — `routes/venues.py:171` vs `services/venue.py:46-54`
- §3.2 — insert — the 72-hour freshness comparison is signed, so a run stamped after the clock passes — `routes/venues.py:236-241`
- §3.2 — insert — **mismatch** — drift-cascade links 2 and 3 fire only when posture stood at `CERTIFIED` immediately before — `services/venue.py:52-53`
- §3.2 — insert — retirement preserves `certified_at_utc`, `certified_by_user_id` and the four latest-run mirrors — `routes/venues.py:279-282`
- §3.3 — insert — `market_code` three-letter shape and uniqueness both unenforced — `routes/clubs.py:19-22`
- §3.3 — insert — `roster_size` refreshes the club's `updated_at`/`version` and is never lowered — `routes/clubs.py:84-85`
- §3.3 — revise — **mismatch** — any `ClubDataOfficer` may read a club; the read carries no ownership check — `routes/clubs.py:57-61`
- §3.3 — insert — `jersey_number` uniqueness within the club unenforced — `routes/clubs.py:24-28`
- §3.3 — insert — consent record echoes `effective_from_utc`/`expires_at_utc` verbatim — `routes/clubs.py:149-150`
- §3.3 — revise — **mismatch** — any `ClubDataOfficer` may page a player's consent records; no ownership check — `routes/clubs.py:170-181`
- §3.3 — insert — `active_consent_record_id` holds one record, overwritten by a ratification of either scope — `routes/clubs.py:206-211`
- §3.3 — insert — a `BIOMETRIC_TRACKING` ratification sets `GRANTED` from any prior state, `WITHDRAWN`/`EXPIRED` included — `routes/clubs.py:209-210`
- §3.3 — insert — ratification never unmasks: `biometric_masked` and both `masked_tag_count`s never fall — `services/consent.py:30-35`
- §3.3 — revise — **mismatch** — withdrawal clears `active_consent_record_id` only when the pointer named the withdrawn record — `routes/clubs.py:238-239`
- §3.3 — insert — the cascade keys on the player's `biometric_release_state`, not the record's scope; not-`GRANTED` stops at link 1 but the player row is still touched — `services/consent.py:17-19`
- §3.3 — insert — already-masked tags are skipped, so a second consent loss never double-counts — `services/consent.py:28-29`
- §3.3 — revise — **mismatch** — lapse clears the pointer under the same only-if-it-named-this-record rule and runs the cascade under the same `GRANTED` guard — `services/consent.py:84-86`

### Pass 3 (games/tags/rights/feeds) — 13 pins, 2 mismatches
- §3.4 — insert — `home_club_id`/`away_club_id` never compared, so a game may name the same club on both sides; `scheduled_start_utc` echoed verbatim — `routes/games.py:52-64`
- §3.4 — insert — closing collection suspends REALTIME sessions without settling: no ledger moves and suspended sessions still count towards `active_feed_session_count` — `routes/games.py:165-172`
- §3.5 — insert — an `UNDER_CORRECTION` tag is not superseded; the new tag is created and the triple carries two live tags — `routes/tags.py:40,110`
- §3.6 — insert — `proposed_clock_ms` must be a non-negative integer — `routes/tags.py:33`
- §3.6 — insert — a `WRONG_PLAYER` approval re-checks roster membership only, never the replacement's `biometric_release_state`, and masks nothing — `routes/tags.py:325-345`
- §3.7 — insert — window bounds echoed verbatim — `routes/rights.py:101-102`
- §3.7 — revise — **mismatch** — a `LEAGUE` window's `holder_id` is never resolved, so any non-null value draws `ERR_RIGHTS_HOLDER_MISMATCH` rather than a 404 — `routes/rights.py:46-51,68-71`
- §3.7 — revise — **mismatch** — `territory` accepted as any string, unvalidated; the `GLOBAL`/two-letter convention is unenforced and feeds only the collision rule — `routes/rights.py:26`, `services/rights.py:24-29`
- §3.7 — insert — revocation mutates the window row exactly once, whatever the number of sessions settled — `routes/rights.py:155-157`
- §3.8 — insert — the acting `X-User-ID` must resolve to a licensee, as the third body-reference lookup → `ERR_LICENSEE_NOT_FOUND` 404 — `routes/feeds.py:153-155`
- §3.8 — insert — `duration_minutes`/`latency_multiplier` persisted and read back; usage records charge against the stored multiplier; bounds echoed verbatim — `routes/feeds.py:251-258,333`
- §3.8 — insert — a usage record's `sampled_at_utc` is echoed verbatim and never required to fall inside the session interval — `routes/feeds.py:350`
- §3.8 — insert — reporting usage never touches the unit ledger; a non-breaching record leaves the licensee row unmutated — `routes/feeds.py:360-374`
- §3.9 — insert — the run echoes `basis`, `metric_code`, `segment_values`; recording it does not mutate the game row — `routes/games.py:274-288`

**Notable non-findings (verified already uniquely pinned):** the full §2.10 ladder matches impl check order in every route file including the non-obvious placements (rank 8 OCC before rank 11 LIVE; rank 23 biometric entitlement ahead of rank 30 tier scope; rank 27 containment and ranks 30–34 latency/transport ahead of rank 39 window/game mismatch; rank 7 SoD ahead of rank 16 on correction resolution). All formula constants match exactly: 15% gross reserve, 300s broadcast buffer, 40/30/22¢ tier rates, 1.50/1.20/1.00 latency tiers at 250ms/1000ms, 0.5/0.3/0.2 QI weights with 1.0/0.25 correction weights and 4 expected tags, 0.8000 floor, 3-breach breaker, 25% SLA credit, scales 1.042/1.017/1.000, drifts −0.6/−0.2/0.0, `MAP-2026.1`. Unit-ledger conservation holds algebraically across admission and settlement. §4 (50 endpoint rows) and §5 (error catalogue) required no row changes in any pass.

**Orchestrator final verification of PRD_COMPLETED.md** (guarding against the byte-identical no-op failure mode):
- `PRD_FINALIZED.md` md5 `b6d339b48aafc3f31287a82fb6301d09` vs `PRD_COMPLETED.md` md5 `ce0ca0beab2f30acdac177cec9b591b9` — **genuinely different**, the scan ran.
- 444 → 445 lines; 95,886 → 109,110 characters, **+13,224 chars**; 89 changed lines in `diff`.
- Tail confirms the file ends on the complete final §5 row `| ERR_SESSION_RESERVATION_EXCEEDED | 402 |` — a real section boundary, not truncated.
- `diff` of the heading sets between `PRD_FINALIZED.md` and `PRD_COMPLETED.md` is empty: all 28 headings present, none added, removed, or renumbered.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written. Final test evidence stands from Step 7: `workspace/implementation/results.{1..8}.json`, each 109/109 passed, 0 failed. Steps 8 and 9 touched only PRD prose — no test or implementation file was modified after the green sweep, so the sweep evidence remains valid.
