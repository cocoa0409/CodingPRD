# Worklog — task_2629_junior_golf_tour_ranking_administration

## Step 1: Create task directory — 2026-09-03T21:51:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2629_junior_golf_tour_ranking_administration` and `.../workspace` (pre-assigned path from orchestrator args; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T23:20:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2629_junior_golf_tour_ranking_administration/`):
- `SCAFFOLD.yaml` — 3095 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1124 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2673 lines (single key `scaffold_corner_design`)

**SCAFFOLD.yaml counts:** 10 entities · 10 state machines / 74 transitions · 3 §1.2.1 OCC rules · 13 calculations · 44 ordered validations · 53 endpoints · 44 errors · 7 roles. Profile: `expert_plus`, flat topology, parallel primary state shape (Entry carries `entry_status` × `fee_status`), `segregation_of_duties` role model, `immediate` consistency, layers `optimistic_concurrency / cascading_side_effects / ops_run_checkpoint / selector_policy`. The scenario text is stored verbatim (verified byte-for-byte against the assignment).

**§1.8:** 9 `rule_id` blocks, 20 instances (dual-variant ranking & assistance, four-factor event points, pinned rounding/settlement order, parallel Entry dimensions, dispute cycle, 5-hop suspension cascade, retroactive DQ cascade, 3 priority pairs, 2 boundary checks, 2 cross-entity gates, 2 temporal-overlap cases, 2 compensating invariants).

**§1.9:** all nine guide sections present, 89 entries = **68 full instances + 21 `excluded_because:` stubs** — entities 11, state_machines 18, calculations 13, validations 20, endpoints 8, errors 7, rbac 5, cross-cutting layers 6, consistency model 1.

**Verification performed:** `scaffold_lint.py` → `VERDICT: clean lint` over 1151 §1.8+§1.9 calls; all 44 catalog errors have at least one trigger; instance names unique across both design files; every stub's cited `difficulty_instance` (`rule_id / name`) resolves in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and carries no `test_recipe`.

Two consistency repairs were made to `SCAFFOLD.yaml` earlier in this session: the §1.5 `conduct-cases/{caseId}/decide` VENUE_BAN bullet now matches §1.2's forfeit semantics (it previously claimed no entry changed), and validation priority 30 no longer lists `IN_PROGRESS` as cancellable. The stale `difficulty_level` comment was also corrected to the real counts. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T23:20:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T23:38:00.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — **471 lines / 113,049 bytes**, written in 11 chunked `cat >>` appends. Ends cleanly at the last row of the §5 table (`| ERR_PAYMENT_AMOUNT_INVALID | 422 |`); no audit footer, no PASS text, no other files created.

## Heading list
Sections 1–5 present: Introduction; Global Specifications (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Identity/Timestamps/Row Versions, 2.5 Logical Tour Clock, 2.6 Order of Refusal, 2.7 OCC on Junior Record, 2.8 Precision/Rounding/Money, 2.9 Ledger Discipline: Season Assistance Purse, 2.10 Slot Census Discipline, 2.11 Cascade Depth and Compensation Asymmetry, 2.12 Path Resolution and Read Projections); Business Logic 3.1–3.9; §4 API Endpoint Definitions; §5 Error Code Catalogue.

## Hard Contract results (all machine-verified)

**Contract 1 — Field-Name Coverage: PASS.** 153 identifiers extracted from the scaffold — 0 missing from backticks in PRD.md. Broader sweep of 209 snake_case tokens: the 74 unmatched are scaffold metadata keys, calculation ids, or expression locals, never client-facing identifiers.

**Contract 2 — Rule Coverage: PASS.**
- 44/44 validations rendered in §2.6 in exact priority order (1→84) with `applies_to` scopes; all 44 validation error ids present.
- 74/74 state-machine transitions covered (48 explicit `A → B` arrows; other 26 in prose, verified individually by grep).
- All 13 calculations rendered with every named constant expressed as its value in prose (44 numeric spot checks: TIER_BASE 150/300/600/800, RANKING_BEST_N/MIN_EVENTS 4, FINISH_DECAY 0.05, FLOOR 0.20, DIFFERENTIAL_PAR 2.0 @ 25 pts/stroke, FQ 0.02/0.01/12/1.60/rank-50 cutoff, aid tiers 1.5M/2.5M/4.5M/7M → 1.00/0.90/0.65/0.40, caps 60000/25000, pace 2/15/2/3, windows 48h/72h/14d/180d/365d, STANDARD_SLOPE 113, UNRANKED_SORT_RANK 999999, LATE_WD 2, surcharge "ten percent").
- §4: 53/53 scaffold endpoints present as exact table rows, 0 role-set mismatches. §5: 44/44 error ids, 0 status-code mismatches.
- §2.2 verified byte-identical to `section-2.2-response-structure.md`.

**Contract 3 — §3 Path Purity: PASS.** Every backticked token in §3 machine-checked: 0 leading-slash tokens, 0 bare HTTP methods, 0 method+path combinations, 0 stray slashes.

## Scaffold inconsistencies found and how resolved
1. `Tournament.field_quality_factor` entity default `1.00` vs `POST /tournaments` side effect `= null` → followed the endpoint (null at scheduling).
2. `POST /members` side effect sets `certified_ranking_points = null`, `last_ranking_epoch = null`, contradicting entity defaults `0.00`/`0` → followed the endpoint.
3. `POST /rules-cases` side effect `penalty_strokes_applied = null` vs entity default `0` → followed the endpoint.
4. `POST /conduct-cases` side effect `cumulative_points_at_decision = null` vs entity default `0` → followed the endpoint.
5. MEMBER_SUSPENSION cascade breadth: decide endpoint side effects mention `COMPETING`→`FORFEITED` and `CONSUMED`→`REVOKED`, which §1.2 does not define → followed §1.2.
6. Validation priority 1 says "X-Role header"; SKILL mandates `X-User-Role` → used `X-User-Role`.
7. `observation_type` enum never fully declared (only `WARNING` referenced) → did not invent members.

Constraints honored: neither design yaml was opened; no sibling task directory read.

Orchestrator verification: `tail -c 900 PRD.md` confirms the document ends at a complete `| ERR_PAYMENT_AMOUNT_INVALID | 422 |` table row — a real section boundary, not mid-sentence. No truncation; no regeneration needed.

## Step 5 + 6: Launched concurrently — 2026-09-03T23:40:00.000Z

Both generator subagents launched and running in parallel:
- Step 5 (unit-test generator) → `test_helpers/` + `test_suite/` at the TASK ROOT (explicitly instructed not to write under `workspace/`).
- Step 6 (implementation generator) → `workspace/implementation/` incl. `start.sh`.

Orchestrator decision recorded: the two Agent calls went out in back-to-back messages rather than one message, so Step 6 did not get guaranteed *physical* isolation from `test_suite/` (the directory may have begun to exist a few seconds into its run). Mitigation applied instead of restarting: Step 6's prompt carries an ABSOLUTE HARD CONSTRAINT — TEST BLINDNESS clause forbidding any read/list/glob/grep/stat of `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and `SCAFFOLD_CORNER_DESIGN.yaml`, restricting it to `PRD.md` + `SCAFFOLD.yaml` + `INSTRUCTION.md` and to working only inside `workspace/implementation/`. Restarting Step 6 was judged strictly worse than the logical constraint: a restart would have serialized the two heavy generations and cost ~20 min of wall clock on a 32-way-contended host for a guarantee the prompt-level ban already provides. Will confirm in the Step 6 summary that no test artifact was read.

## Step 6: Generate implementation — 2026-09-04T00:11:00.000Z

The implementation is complete and verified.

## Files — `workspace/implementation/`

| lines | file | role |
|---|---|---|
| 8 | `start.sh` (executable) | `cd $(dirname $0)`, guarded `if ! python3 -c "import flask"` install, `exec python3 app.py` |
| 1 | `requirements.txt` | `Flask>=2.2` |
| 62 | `app.py` | blueprint registration, ApiError/HTTPException/500 handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
| 211 | `store.py` | in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), id/ISO-3dp helpers, `bump()` (one version increment per row per request) |
| 115 | `errors.py` | all 44 error ids → HTTP status + default messages |
| 52 | `envelope.py` | `meta`/`response_type`/`data`; pagination fields in `meta` on lists only |
| 192 | `validate.py` | ERR_INVALID_REQUEST schema layer + pagination (limit 1..100 default 10, offset >= 0) |
| 86 | `auth.py` | `X-User-Role`/`X-User-ID`, 7 roles, ownership + live-coach-grant checks |
| 290 | `calc.py` | all 13 calculations, `Decimal` + ROUND_HALF_UP, pinned constants |
| 680 | `services.py` | census/field-quality/waitlist, ledger movements, roll-ups, rankings, completion, forfeit/withdraw/cancel, DQ + conduct cascades |
| 50 | `listing.py` | conjunctive filters, `created_at` ASC ordering, paging |
| 292 / 296 / 349 / 453 / 278 | `routes_core.py`, `routes_tournaments.py`, `routes_entries.py`, `routes_rounds.py`, `routes_cases.py` | the 53 endpoints |

Total 3415 lines. Every file compiles (`python3 -m py_compile`). `app.url_map` exposes exactly 53 routes (+ Flask's `/static`), matching the PRD §4 table one-for-one. No seeding, no disk persistence (`grep` for `open(`/sqlite/pickle/`/tmp` is empty).

## Smoke test (PORT=18629, only the PIDs started were killed)

Boot to first 200: **0.68 s**; fresh process serves an empty store. Two end-to-end scenarios plus an error-probe pass, all green (0 failures):

- **Pinned figures reproduced exactly**: covered_pct 0.90 → estimate **22500** vs settlement **28800**; late surcharge **3200** on a 32000 fee → net due **6400**, fee_status AID_PARTIAL; differentials **-4.8 / 0.5** → avg **-2.2** (double rounding); REGIONAL fqf 1.00, finish 1 → event_points **405.00**; provisional **405.00** vs certified **101.25** with rank 1; ledger invariant held (71200 + 0 + 28800 = 100000 budget).
- **Mechanics exercised**: selector/waitlist (2 accepted, 1 waitlisted, open_slot 0), withdrawal → REFUNDED + waitlist promotion, pace penalty capped at 3, three-dispute cycle → NO_CARD with null adjusted_gross, rules case penalty (+2 strokes, adjusted 77) → appeal granted reverses to 0, certification blocked by open case (409), SoD 409 on self-adjudication and self-certification, retroactive DISQUALIFICATION (event_points 0.00, finish_position null, finished_count -1, accepted_count unchanged), conduct tiers (3 → VENUE_BAN_ONE_EVENT, 6 → MEMBER_SUSPENSION with 5-hop cascade), appeal → CLEARED reinstates to VERIFIED with conduct_points 0, coach grant supersede/decide/revoke gating published-results (200 → 403), tournament cancel compensation.
- **Envelope/plumbing probes**: 401 bogus role, 403 RBAC + ownership, 404 `ERR_NOT_FOUND`/`ERR_TOURNAMENT_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`, 412 `ERR_STALE_MEMBER_VERSION`, 422 malformed JSON / missing field / `limit=0`, 409 duplicate entry, tee-slot full at group size 3.

Test blindness was maintained: nothing under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task was read or listed. (This resolves the Step 5/6 isolation note above: the prompt-level ban held.)

Two judgement calls flagged by the generator: `narrative` on `POST /conduct-cases` is treated as required (endpoint input list has no `?`, and PRD prose lists it among the filer's inputs, though the entity default is null), and the submit-score fee gate raises `ERR_ENTRY_FEE_OUTSTANDING` (PRD names the rule but not the error id; the endpoint's declared error list omits it).

## Step 5: Generate unit tests — 2026-09-04T00:44:00.000Z

The suite is complete.

## Output (both directories at the TASK ROOT)

`test_helpers/` — 1,649 lines: `__init__.py` (15), `types.py` (165), `api_errors.py` (116, includes `set_error_http_status_map`), `constants.py` (111), `api_client.py` (210), `test_users.py` (70), `assertions.py` (181), `factories.py` (328), `fixtures.py` (453).

`test_suite/` — 5,028 lines, 18 test files + `conftest.py` (18):

| file | lines | tests |
|---|---|---|
| test_01_dual_ranking_and_assistance_variants.py | 184 | 4 |
| test_02_event_points_and_fee_settlement_order.py | 233 | 6 |
| test_03_entry_dimensions_and_dispute_cycle.py | 211 | 4 |
| test_04_suspension_and_disqualification_cascades.py | 274 | 4 |
| test_05_refusal_priority_conflicts.py | 263 | 6 |
| test_06_pace_thresholds_and_empty_fields.py | 144 | 4 |
| test_07_guards_on_neighbouring_entities.py | 159 | 4 |
| test_08_tee_sheet_and_travel_windows.py | 168 | 4 |
| test_09_compensating_reversals.py | 209 | 4 |
| test_10_registration_reads_and_stored_shape.py | 376 | 11 |
| test_11_lifecycle_transitions.py | 501 | 13 |
| test_12_derived_figures.py | 439 | 8 |
| test_13_entry_and_money_gates.py | 665 | 14 |
| test_14_endpoint_projections_and_actions.py | 256 | 6 |
| test_15_error_codes.py | 374 | 7 |
| test_16_role_authority.py | 306 | 5 |
| test_17_member_version_guard.py | 159 | 3 |
| test_18_immediate_consistency.py | 89 | 1 |

## Verification (all machine-checked)

- **108 tests, 108 `Design:` tags** — every test has exactly one, as the last docstring line, and every tag resolves to a real instance. Zero untagged, dual-tagged, unresolved, or stub-tagged tests.
- **Queue A (§1.8): 20/20 instances, exactly 40 tests** — every instance has >=2.
- **Queue B (§1.9): 68/68 non-stub instances covered, 68 tests** — every instance has >=1.
- **21 `excluded_because:` stubs emitted nothing**; all 21 cross-references resolve to real, non-excluded §1.8 instances.
- No `skip` / `skipif` / `xfail` anywhere; no mention of "scaffold" in any generated file.
- `pyflakes` clean (rc 0); `pytest --collect-only` → **108 tests collected**, no import errors.
- `ls -d` confirms both dirs at the task root; `find workspace/ -name test_helpers -o -name test_suite` returns nothing. Nothing under `workspace/implementation/` was read or written.

## Design-vs-PRD conflicts resolved in favour of the PRD (instance still translated, never weakened)

1. `expired_or_foreign_exemption_grant_is_not_applicable` — recipe wanted the lapsed grant to stay `ACTIVE`; PRD §3.2 lazily marks it `EXPIRED` at read time, so the test asserts `EXPIRED`.
2. `ranking_read_of_a_member_with_no_results_is_all_zeros` — recipe wanted `certified_ranking_points == 0.00` / `last_ranking_epoch == 0`; PRD §3.1 says both start null, so the test asserts `is None`.
3. `handicap_older_than_the_validity_window...` — recipe verified a member whose handicap was already 181 days stale, but PRD §3.1 refuses verification itself; restructured to verify at clock `2026-07-01` and move to `2026-08-10` for the entries, pinning the exact 180-day edge (`2026-02-11` accepted, `2026-02-10` refused).
4. All exact-timestamp equality assertions use `.startswith(...)` because §2.4 mandates three fractional digits.

## Note carried forward

The shared `/tmp/dump_corner.py` was overwritten mid-run by a concurrent sibling agent and briefly returned another task's design content (task_2630); that output was discarded unused and the agent switched to its own `/tmp/dump_corner_2629.py` loading task_2629's yaml by absolute path. No sibling task directory was otherwise read.

Orchestrator verification: `ls -d test_helpers test_suite` at the task root confirms both present with 18 test files + conftest.py; `find workspace -name test_suite -o -name test_helpers` returns nothing — no stray copies under workspace/.

## Step 7: Run tests and iterate — 2026-09-04T01:05:00.000Z

All 8 rounds of the final sweep are green: 108/108 in every round.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep #1: 97/108 in all 8 rounds, 11 deterministic failures, zero flakiness; sweep #2 after fixes: 108/108 in all 8 rounds).

**Verification:** `workspace/implementation/results.{1..8}.json` (all written 01:00, each `passed == total == 108`).

**Tests deleted:** none. Every failure resolved to a test-side infidelity or an implementation defect; no test failed STEP 1a coverage or STEP 1b unique derivability.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — new `build_tee_sheet()` helper plus a `round_row=` passthrough on `play_round()`, and `completed_event()` now builds each day's whole tee sheet before any card is played. Why: PRD §3.6 requires a round's marker to "hold an `ACCEPTED` or `COMPETING` entry in the same tournament", and PRD §3.7 moves an entry to `FINISHED` on its last certification — the old fixture certified junior A's final round and *then* created junior B's card naming A as marker, so it violated the PRD precondition it was supposed to satisfy. (7 of the 11 failures were this one `ERR_INVALID_MARKER`.)

**Fixes applied to `test_suite/`**
- `test_02_event_points_and_fee_settlement_order.py::test_national_win_and_runner_up_are_not_a_scaling_of_one_another` and `test_11_lifecycle_transitions.py::test_only_the_last_certification_completes_the_event` — same marker-ordering correction, using `fx.build_tee_sheet`.
- `test_04_suspension_and_disqualification_cascades.py::test_sanctioned_altercation_forfeits_the_slot_and_backfills_the_waitlist` — asserted exemption-grant status changed `REVOKED` → `CONSUMED`. The grant had already been consumed at the selector run, and PRD §3.9 revokes only grants "whose `status` is `ACTIVE`", while §2.10/§3.5 state "a forfeiture leaves it `CONSUMED` forever" / "A consumed exemption grant stays `CONSUMED`: forfeiture never restores an exemption". The old assertion contradicted the PRD.
- `test_15_error_codes.py::test_an_upheld_rules_case_cannot_be_adjudicated_twice` — the second adjudication payload omitted `disposition`, which PRD §3.7 lists as carried (only `penalty_strokes_applied` is optional), so schema validation correctly fired `ERR_INVALID_REQUEST` ahead of the state gate. Added `disposition=DISPOSITION_PENALTY_STROKES` so the test actually reaches the `ERR_INVALID_CASE_STATE` gate it means to assert.

**Fixes applied to `implementation/`**
- `workspace/implementation/store.py` — `iso()` now renders second-precision ISO 8601 UTC (`...T00:00:00Z`) and a new `iso_ms()` keeps the three-fractional-digit form, which `wall_iso()` uses. Why: PRD §2.2 grants three fractional digits explicitly to `created_at`/`updated_at` (and `api_request_timestamp`) but describes the business-event stamps (`submitted_at`, `certified_at`, `decided_at`, `expires_at`, `tee_time`, ...) only as "ISO 8601 UTC instants", writing every one of them at second precision; the implementation was appending `.000` to those, breaking exact-instant assertions on `expires_at` (coach grant, 180-day term) and `tee_time`.

No implementation check was weakened, no assertion downgraded, no skip/xfail added, and storage remains in-memory dicts with an empty store on every boot.

Orchestrator verification (independent of the subagent's claim): `ls -la results.*.json` shows all 8 files present at 01:00, and a JSON read of each confirms `passed=108 / total=108 / failed=0`. Sweep artifacts are real; the clean-sweep claim is substantiated.

Step 8 will run (Step 7 applied 1 `implementation/` fix, 3 `test_suite/` fixes and 1 `test_helpers/` fix, so the skip condition does not hold).

## Step 8: Finalize PRD — 2026-09-04T01:12:00.000Z

## Line counts
- `PRD.md`: 471 lines / `PRD_FINALIZED.md`: 471 lines — **0.0% line delta** (one paragraph extended in place; tail still ends at `| ERR_PAYMENT_AMOUNT_INVALID | 422 |`).

## Changes (1)
- **§2.4 Resource Identity, Timestamps and Row Versions** — *insert* — pinned timestamp **rendering precision**: three fractional digits belong to `created_at`/`updated_at`/`api_request_timestamp` alone, every other instant the API stores or returns is whole-second `YYYY-MM-DDTHH:MM:SSZ`, and client-supplied instants are normalised into that canonical form (offset converted to UTC, fractional part discarded) — `implementation/store.py:58-93` (`iso` vs `iso_ms`/`wall_iso`), `implementation/validate.py:135-147` (`req_dt` → `iso`).

## Pre-edit search log

**Edit 1 — subject: rendering precision / canonical form of every timestamp-valued field in requests and responses.**

(b) Paths enumerated and read/grepped:
- `store.py:58-73` `iso()` (second precision, truncating), `store.py:76-84` `iso_ms()`, `store.py:87-93` `wall_now`/`wall_iso`, `store.py:96-106` `clock`/`clock_iso`/`set_clock`, `store.py:112-159` `_DT_RE`/`parse_dt_str`/`dt_of` (accepts offsets, optional seconds, fractions).
- Exhaustive grep of every `iso(`/`iso_ms(`/`wall_iso(`/`clock_iso(` callsite: `envelope.py:19` (`api_request_timestamp`), `store.py:176,187,231` (`created_at`/`updated_at` on insert and both `bump` paths), `routes_cases.py:101,119,134,213,256,257,260`, `routes_core.py:290,292`, `routes_entries.py:166,347`, `routes_rounds.py:239,373,389,413`, `services.py:364,482,525,545`.
- Every `validate.req_dt`/`opt_dt` callsite (client-supplied instants): `routes_core.py:289` (`current_utc`), `routes_rounds.py:54` (`tee_time`), `routes_tournaments.py:46-48` (`entry_open_at`/`entry_close_at`/`withdrawal_deadline_at`), `routes_tournaments.py:248` (exemption-grant `expires_at`, client-supplied and stored verbatim at line 271).
- Exhaustive grep of all `"*_at"`, `"*_time"`, `"*_utc"`, `"*_date"` field literals across all impl modules to prove the inventory closed: the only instant-valued fields are the ones named; `age_cutoff_date`, `as_of_date`, `birth_date`, `end_date`, `handicap_effective_date`, `last_ranking_as_of_date`, `ranking_window_start_date`, `start_date` are `YYYY-MM-DD`, so the universal claim excludes nothing it should include.
- Cross-checked existing PRD statements touching the same subject so the new sentence does not contradict them: envelope examples (`.123Z`), `api_request_timestamp` three digits, `created_at`/`updated_at` three digits, clock default `2026-08-01T00:00:00Z`, tournament calendar instants, `tee_time`, coach-grant `expires_at` = `decided_at` + 180 days (already pinned).

(c) Wording adjustments made: (i) scoped the three-digit form to an explicit closed list rather than "audit fields", because `api_request_timestamp` is an envelope field, not a row field; (ii) widened "every other instant" to name the client-supplied tournament calendar instants, `tee_time`, and `current_utc`/`previous_utc`, so the sentence is not read as covering only the Step 7 sites; (iii) added the normalisation clause as a separate sentence covering the shared `req_dt` helper; (iv) said "discarded" rather than "rounded" to match `iso()`'s truncation; (v) said "rendering"/"is rendered" rather than "is stored at" to avoid claiming anything about internal storage the impl does not exhibit.

## Items deliberately not patched (PRD already uniquely determines them)
- Marker precondition ordering (`fixtures.py`, `test_02`, `test_11`): PRD already states the marker "must themselves hold an `ACCEPTED` or `COMPETING` entry in the same tournament", matching `routes_rounds.py:72-84`. Pure fixture bug.
- Exemption-grant status after a sanction forfeiture (`test_04`): PRD already pins `CONSUMED` staying `CONSUMED` and only `ACTIVE` grants moving to `REVOKED`, matching `services.py:118-133,645-648`.
- `disposition` required on rules-case adjudication (`test_15`): PRD already lists it as carried with only `penalty_strokes_applied` optional, matching `routes_rounds.py:344-347`.

## Step 9: Complete PRD — 2026-09-04T01:45:00.000Z

Orchestrator decision: Step 9 was run as **three sequential file-partitioned passes** over the same `PRD_COMPLETED.md`, rather than one subagent scanning all 15 implementation modules. Rationale: the implementation is 3415 lines across 15 modules; a single-agent exhaustive walk reliably degrades into a shallow skim (or produces a byte-identical copy of its source, i.e. no scan at all). Partitioning by file guarantees every module is actually read by an agent with room to hold it, and each pass received the previous passes' hand-off notes so cross-module behaviors were not lost at the seams. Pass 1 created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; Passes 2 and 3 edited it in place and verified the earlier passes' edits survived.

### Pass 1 — app.py, store.py, errors.py, envelope.py, validate.py, auth.py, listing.py, routes_core.py, routes_tournaments.py
Copied from `PRD_FINALIZED.md`. **17 ambiguity-pins, 3 mismatch-revisions (20 edits).** Highlights:
- §2.1 — absent role header reads as `Anonymous` on the two public endpoints; unrecognised role name → `ERR_UNAUTHORIZED` (403), not `ERR_UNAUTHENTICATED` (auth.py:37-45). Absent `X-User-ID` is not itself an auth failure (auth.py:76-86).
- §2.2 — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters (envelope.py:12-13).
- §2.3 — `created_at` ties fall back to creation order, no `id` tie-break (store.py:198-200); filter semantics: empty value = omitted, undeclared params ignored, uncoercible value matches nothing without erroring (listing.py:9-38).
- §2.4 — **mismatch**: `created_at`/`updated_at`/`api_request_timestamp` come from the host wall clock, not the logical clock; `version` advances at most once per row per request (store.py:175-189, 217-234). Accepted client ISO spellings pinned (store.py:113-154).
- §2.6 — **mismatch**: exemption-grant single read added to the ownership-guarded list; a grant-less `Coach` sees `ERR_FORBIDDEN_RESOURCE` on the single-member read but `ERR_COACH_ACCESS_DENIED` on the ranking/published-results views.
- §3.1 — `guardian_email` 1–320 chars, length-checked only; `handicap_index` stored verbatim and always rendered fractional (`12` → `12.0`); `note` on verify is 1–2000 and not persisted; re-deciding a decided junior → `ERR_INVALID_REQUEST` (422).
- §3.2 — **mismatch**: `source_tournament_id` is not coupled to `category`; `expires_at` unconstrained; duplicate `ACTIVE` grants for the same pairing permitted (routes_tournaments.py:249-277).
- §3.9 — **mismatch**: coach-grant `scope` is recorded but not enforced at read time (auth.py:59-73).
- §4 intro — framework refusals `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INTERNAL` 500; trailing slashes tolerated (app.py:22, 33-52).

### Pass 2 — calc.py, services.py
**14 ambiguity-pins, 4 mismatch-revisions (18 edits).** Highlights:
- §2.9 — **mismatch**: disqualification moves no money, so a DQ'd assisted entry's award stays in `assistance_committed_cents` forever (services.py:588-603, 469-471). Forfeiture and completion do not clear the entry's own `aid_award_cents`; only withdrawal/cancellation zero it.
- §2.11 — **mismatch**: a cascade hop that recomputes a derived field to the value it already holds is not a mutation — no `updated_at`, no `version` (waitlist renumber, finish positions, event points, provisional/certified figures).
- §3.2 — once the clock passes `expires_at`, grant consumption silently does not fire: grant stays `ACTIVE`, is not marked `EXPIRED`, no error, entry still takes the slot (services.py:117-127). The automatic qualifier mint applies none of the hand-mint gates.
- §3.5 — withdrawing an `UNPAID` entry leaves `fee_status` `UNPAID` and `net_fee_due_cents` standing; promotion tests `VERIFIED` on the head of the queue only (an unverified head blocks promotion entirely); cancellation leaves `net_fee_due_cents` standing and does not renumber the waitlist.
- §3.8 — **mismatch** ×2: `status` flips to `COMPLETED` before the provisional step (the pool admits only `COMPLETED` tournaments); the seventh step stamps `completed_at`, recomputes the census and bumps `version`. Ranking window is the *junior's own* season's; a junior with an empty pool keeps prior certified figures and only loses `certified_rank_position`.
- §3.9 — 365-day decay window inclusive at its far edge; venue-ban and suspension forfeitures are the §3.5 forfeiture hop-for-hop minus the late-withdrawal charge.

### Pass 3 — routes_entries.py, routes_rounds.py, routes_cases.py
**26 ambiguity-pins, 9 mismatch-revisions (35 edits).** Highlights:
- §2.6 — **mismatch**: recruiting-grant single read added to the ownership list with `ERR_FORBIDDEN_RESOURCE` for a foreign coach; `ERR_ENTRY_FEE_OUTSTANDING` also guards score submission and is the weakest of four gates there.
- §2.11 — the no-op-mutation list is exhaustive; the entry roll-up is deliberately excluded, so it always bumps the entry.
- §2.12 — **mismatch**: corrected filter lists (rules cases 6, conduct cases 7, recruiting grants 5).
- §3.4 — exemption checks run ACTIVE → owner/tournament → expiry; junior and tournament `season_id` are never compared; `ERR_AID_ALLOCATION_EXHAUSTED` also fires for a zero-fee event; both payment state tests precede the amount check.
- §3.6 — **mismatch** ×4: tee-slot occupancy counts every round of the tournament in the window regardless of `round_number` or `status`; submit-score gate order is tournament → entry → round → fee; the third dispute clears both `adjusted_gross` and `scoring_differential` to null. `observation_type` is free text 1–40, not an enum.
- §3.7 — **mismatch** ×2: the entry roll-up is a full recomputation from the entry's CERTIFIED rounds, not an increment; FINISHED requires `certified_round_count >= round_count` **and** `entry_status == "COMPETING"`, with census recomputation, the tournament bump and the completion check all inside that branch. DQ branch does not re-run the entry roll-up; a dismissal never writes the case `disposition`; an appealed dismissal can never be upheld; 48h reopen and 72h appeal windows are inclusive; `open_rules_case_count` decrements floored at zero.
- §3.9 — **mismatch** ×2: `CLEARED` is not terminal, any decided case is appealable (`CLEARED → APPEAL_OPEN` legal); revoke `reason` validated but never stored and the grant list applies no coach narrowing. Conduct-case filing passes no state gate; `narrative` 1–4000; appeal outcomes preserve `cumulative_points_at_decision`.

No Pass 1/2 pin required correction; Pass 3 confirmed §3.7's DQ prose does not reintroduce a money claim contradicting §2.9's exception.

### Orchestrator verification
- `PRD.md` 471 lines / 113,049 B → `PRD_FINALIZED.md` 471 / 113,705 B → `PRD_COMPLETED.md` 471 / 137,306 B.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (the scan genuinely ran; not a byte-identical copy).
- 61 changed lines vs `PRD_FINALIZED.md`; +23,601 bytes of pinning prose, all in-paragraph (line count unchanged, no new sections).
- `tail -2` confirms the document still ends at the complete final table row `| ERR_PAYMENT_AMOUNT_INVALID | 422 |` — no truncation across 73 edits.
- Step 9 touched only `PRD_COMPLETED.md`; `implementation/` and the test suite are unchanged since the green sweep, so `results.{1..8}.json` (108/108 each) remain valid.

## PIPELINE COMPLETE — 2026-09-04T01:45:00.000Z

All nine steps done. Final state: 108 tests, 8/8 sweep rounds at 108/108, 0 tests deleted, `workspace/PRD_COMPLETED.md` written.
