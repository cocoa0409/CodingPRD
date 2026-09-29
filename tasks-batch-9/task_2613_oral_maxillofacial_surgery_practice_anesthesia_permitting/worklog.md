# Worklog — task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting

## Step 1: Create task directory — 2026-09-03T20:02:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/` and its `workspace/` subdirectory. Index 2613 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T21:56:00.000Z

All three scaffold artifacts for task 2613 are complete and pass the lint clean.

## Output files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3278 | §1.0–§1.7: 14 entities, 9 state machines, 3 concurrency rules, 11 calculations, 41 ordered validations, 65 endpoints, 40 errors, 7 roles. No `scaffold_difficulty_design` / `scaffold_corner_design` keys. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2567 | §1.8 only: all 9 `rule_id`s, 25 instances (>=2 each). |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3515 | §1.9 only: all nine guide sections — entities 15, state_machines 16, calculations 17, validations 12, endpoints 6, errors 20, rbac 5, complexity_layers 6, consistency_model 1 (95 instances: 59 full recipes + 36 `excluded_because` stubs citing §1.8). |

Profile: `compliance_audit` x `temporal_windowing`, flat topology, branching state machines, `segregation_of_duties` roles, immediate consistency, expert difficulty; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `derived_field_reconciliation`. The scenario text is stored verbatim. No sibling task was read.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1024

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Defects found and fixed while finishing §1.9

- **22 illegal drill fixtures**: `participant_staff_ids` had a single member, violating this scaffold's own §1.4 priority-5 constraint (`length >= 2`). Fixed across 7 instances; three of them gained a `RECOVERY_NURSE` staff member, which also makes the "staffing checks 1–5 all pass" and "matrix check 1 fired" asserts true rather than merely plausible.
- **Untriggerable/untestable endpoint**: `POST /implant-reservations/{reservationId}/consume` had no recipe anywhere. Replaced a `derived_field_reconciliation` stub with a real reserve → consume → reserve → release recipe; all 65 §1.5 endpoints are now exercised by at least one recipe (verified mechanically), and 20 previously untouched GET reads are covered by three new `retrieval_and_listing` instances.
- **`benefit_allocation` spec hole**: on route `MEDICAL_PRIMARY` (dental plan inactive) the medical-first branch still ran the dental residual pass against `dental_annual_remaining_snapshot_cents`, which defaults to 150000, so a patient with no dental plan could be paid dental money. The branch is now guarded by `if route == 'SPLIT'`.
- `ERR_STAFFING_RATIO_UNMET` was the one error with no §1.8 coverage; it got a real §1.9 recipe (`minimal_sedation_case_without_a_monitor_rejected`).
- One "simultaneously" in §1.8 prose reworded (checklist bans race vocabulary); all three files re-scanned clean.

Other mechanical checks run and passing: every error id reachable, zero unbound `${var}` in either design file, no duplicate instance names across the two design files, every stub's `difficulty_instance` resolves to a real §1.8 instance and carries no `test_recipe`, all `grounds[*]` resolve to declared §1.1–§1.7 elements (4 malformed `endpoints.POST_x_y` refs in §1.8 normalized to `endpoints["POST /path"]`).

## Step 3: Copy shared files — 2026-09-03T21:56:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T22:14:00.000Z

Orchestrator truncation check (per pipeline instruction): PRD.md is 433 lines; `tail -25` ends on the final row of the §5 Error Code Catalogue table (`ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED | 409`), i.e. a real section boundary, not mid-sentence. Independently verified 40/40 scaffold error ids present in PRD.md (only unmatched token is the scaffold's own `ERR_XXX` template placeholder). No regeneration needed.

Subagent summary (verbatim):

PRD.md is complete: `/home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/workspace/PRD.md` — 433 lines / 115,201 bytes, built entirely with chunked appends, ending at the last row of the §5 table (no truncation, no audit footer inside the file).

Structure: §1 Introduction → §2 Global Specifications (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Identity/`version`, 2.5 Logical Clock, 2.6 Validation Order, 2.7 OCC on shared parents, 2.8 Numeric precision/rounding, 2.9 Practice scope, 2.10 Privilege cascades) → §3 Business Logic (3.1–3.10) → §4 Endpoint Definitions (4-column table) → §5 Error Code Catalogue (2-column table).

## Hard Contract 1 — Field-Name Coverage: PASS
- All 131 entity field names across the 14 entities (Practice, AnesthesiaPermit, FacilityInspection, EmergencyDrill, StaffMember, Patient, BlockTime, SurgicalCase, PreAnesthesiaEvaluation, BenefitDetermination, ImplantLot, ImplantReservation, AdverseEvent, ImagingStudy) appear verbatim in backticks. Verified mechanically: extracted every `- name:` under `entities:` and diffed against the set of backticked snake_case tokens in PRD.md — zero missing.
- All endpoint `input`/query/filter field names appear in backticks — zero missing.
- All computed-output keys verified individually: compliance-summary (`practice_id`, `sedation_privilege_state`, `open_permit_id`, `permit_status`, `permit_level`, `required_drill_types`, `covered_drill_types`, `drill_compliance_ratio`, `drill_compliant`, `open_adverse_event_count`, `consignment_committed_cents`, `consignment_credit_limit_cents`), clock (`current_utc`, `previous_utc`), sweep (`swept_at`, `permits_expired`, `permits_suspended`, `permits_expired_ids`, `permits_suspended_ids`, `blocks_released`, `blocks_partially_released`, `cases_cancelled`, `reservations_released`), plus `id`/`created_at`/`updated_at`/`version` and the four pagination keys.
- Path parameters are covered by the §4 table's path column. Every enum literal in the scaffold appears in PRD.md; the only uppercase tokens not carried over are scaffold-internal constant *names* (e.g. `PERMIT_RANK`, `TIER_1_RATE`, `DOSE_REFERENCE_LEVEL`), whose *values* are all stated in prose.

## Hard Contract 2 — Rule Coverage: PASS
Expressed in prose: all 9 state machines (AnesthesiaPermit, FacilityInspection, BlockTime, SurgicalCase.`scheduling_status`, SurgicalCase.`clearance_status`, PreAnesthesiaEvaluation, BenefitDetermination, ImplantReservation, AdverseEvent) including every transition, precondition, side effect and terminal state; all 11 calculations (`drill_compliance_ratio`, `inspection_score`, `block_utilization`, `pre_anesthesia_risk_score` in both provisional and final variants, `staffing_requirement`, `recovery_bay_concurrency`, `benefit_route`, `benefit_allocation` per-line waterfall with per-line round-half-up, `consignment_liability` with the tiered restocking fee, `implant_auto_size_selection` four-key ordering, `imaging_retention_until`); all 41 validation priorities with their explicit orderings (universal 1–10 prefix in §2.6; six-gate hold-block order, eleven-gate confirmation order, three day-of gates, four reservation gates, submit gates in §3); all 3 OCC rules (`expected_block_version`, `expected_lot_version`, `expected_case_version` → 412); every `applies_to` scope, field default, and the 5-hop suspension cascade plus its sweep variant.

Scaffold-internal contradictions resolved (decisions stated once, consistently): NPO minutes anchored to the logical clock at verification (2 of 3 mentions); `ERR_PERMIT_LEVEL_INSUFFICIENT` before `ERR_STAFFING_RATIO_UNMET` per the priority table; lot expiry gated only on `expiry_date` after `planned_start` (the "within 30 days" clause dropped as contradicted by three other sites); auto-size length as +/-2.0 mm inclusive tolerance; ImplantLot `status` limited to `AVAILABLE`/`QUARANTINED` per the field constraint (a stray `EXPENDED` mention in the selector text has no enum backing); the sweep cascade written as cancelling non-terminal sedated cases with `cancellation_reason` `PRIVILEGE_SUSPENDED` (corroborated by the `cases_cancelled` output and the enum value) and explicitly distinguished from the inspection-driven reversion.

## Hard Contract 3 — §3 Path Purity: PASS
Scanned lines 140–315 (all of §3): zero backticked paths, zero backticked HTTP methods, and zero bare occurrences of GET/POST/PUT/PATCH/DELETE anywhere in the section. Every endpoint is referenced by state-transition framing, role plus action verb, or capability description. HTTP methods and paths appear only in §4's table. The only code fences in the document are the two JSON blocks inside the fixed §2.2 block, which is byte-identical to `section-2.2-response-structure.md`. No fuzzy words and no pseudocode operators anywhere in the file.

Table integrity: §4 lists 65 endpoint rows, diffed method-and-path against the scaffold's 65 `endpoints:` entries with an empty diff (the scaffold contains 65, not 64). §5 lists all 40 error IDs with matching HTTP statuses, diffed against the scaffold's `errors:` block with an empty diff.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5 & 6: Launched concurrently — 2026-09-03T22:16:00.000Z

Orchestrator note (decision recorded per AUTONOMY clause): the unit-test generator (Step 5) and the implementation generator (Step 6) were dispatched as two background subagents seconds apart rather than in one assistant message. To preserve the physical isolation the skill relies on, the Step 6 prompt carries an explicit hard prohibition on reading, listing, globbing or grepping `test_helpers/` and `test_suite/` (as well as both SCAFFOLD design indices and any sibling task dir). Step 6 also never received the "Generate task harder than expert level!" difficulty line, which was passed to Step 2 only.

## Step 5: Generate unit tests — 2026-09-03T22:53:00.000Z

Orchestrator verification: `test_helpers/` (2321 lines) and `test_suite/` (8716 lines, 20 entries) are at the task root; neither `workspace/test_helpers` nor `workspace/test_suite` exists, so no relocation was needed.

Subagent summary (verbatim):

Suite complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/`:

## Output
- `test_helpers/` — 9 modules, 2321 lines (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`), unchanged since Stage 1.
- `test_suite/` — `conftest.py` + 18 test files, 8671 lines, **113 tests**, all collected by pytest (`113 tests collected`), all `py_compile`-clean, `pyflakes`-clean, and every module imports cleanly (so every helper/`api_client` symbol referenced actually exists — verified by attribute introspection too).

Files I wrote directly (queue A, 50 tests): `test_01_risk_scoring_variants.py` ... `test_08_cross_entity_state_dependencies.py`, plus this session's `test_09_resource_temporal_overlap.py` (6 tests) and `test_09_compensating_invariants.py` (6 tests). Queue B was partitioned across three subagents: `test_10`-`test_13` and `test_14`-`test_17` (63 tests).

## Audit results (machine-checked over all 18 files)
- **Difficulty coverage:** 25/25 instances, each with exactly 2 tests. No stubs in the difficulty index.
- **Corner coverage:** 63/63 non-stub instances, each with >=1 test. All 35 `excluded_because:` stubs left untranslated; no stub carries a `Design:` tag, and every stub's `difficulty_instance` pointer resolves to a real difficulty instance name (no broken pointers).
- **Tagging:** 113 `Design:` lines for 113 tests — exactly one per test, always the last docstring line, no untagged/dual-tagged tests, no tag pointing at a non-existent instance.
- **Citations:** every quoted PRD fragment (>=40 chars) is a literal whitespace-normalised substring of `workspace/PRD.md`. Zero failures.
- **No `pytest.mark.skip` / `skipif` / `xfail` / placeholders anywhere.** No leakage of design-doc vocabulary ("scaffold", ".yaml"); the only section-symbol occurrences are inside verbatim PRD quotes.

## Design-vs-PRD conflicts resolved this session (PRD wins; no assertion weakened)
1. `resource_temporal_overlap/monitor_half_open_overlap_without_buffer` — the recipe holds all three cases before confirming, but PRD gate 10 counts `BLOCK_HELD` cases too, so the straddling case would have blocked confirmations 1 and 2. Reordered setup (hold/clear/confirm the two back-to-back cases, then introduce the straddler); every asserted literal preserved (60/60/60 committed, case 3 `BLOCK_HELD`, eval 1 `final_risk_score` 16.0/LOW).
2. `compensating_invariant/block_minute_conservation_on_cancel` — the recipe's fasting instants (solids 05:00, clock 12:00 -> 420 min) trip the unconditional +15 penalty and contradict its own asserted `final_risk_score == 10.0`. Set solids exactly at the 480-minute floor, which reproduces 10.0/LOW as designed. LOCAL_ONLY correctly skips the fasting *gate* while the *penalty* stays unscoped.

Earlier-session equivalents (also PRD-first, values preserved by moving the clock to the operative hour): the two npo recipes in `dual_variant_calc` and `boundary_precision_check`.

## PRD gaps worth flagging upstream
- Confirmation gate 6 reads "the open permit's `drill_compliance_ratio`" but several LOCAL_ONLY recipes confirm at practices holding no permit at all; gates 4/5 carve LOCAL_ONLY out explicitly, gate 6 does not, and no behaviour is defined when no permit row exists.
- Two `errors` stubs both defer to the single difficulty instance `auth_9_beats_fasting_safety_62`, so the escort gate risks being untested suite-wide (it is in fact covered by my `test_06` third test, which walks auth -> fasting -> escort -> success).
- `required_drill_types` array *order* is not PRD-derivable (only membership), and `issued_at` on the PROBATION inspection branch is stated both ways in the design vs PRD §3.3 — the PRD reading (stamped on both branches) was used.

## Step 6: Generate implementation — 2026-09-03T22:56:00.000Z

Subagent summary (verbatim):

The implementation is complete and verified.

## What was done

Wrote the final missing module, `/home/ubuntu/github/CodingPRD/tasks/task_2613_oral_maxillofacial_surgery_practice_anesthesia_permitting/workspace/implementation/app.py`, then ran the mandated verification sweep.

`app.py` (106 lines):
- Registers all 11 blueprints (practices, permits, directory, blocks, cases, evaluations, benefits, implants, events, imaging, ops) at the flat top-level topology the scaffold specifies (`api_prefix: ""`), with `strict_slashes = False`.
- `before_request`/`teardown_request` acquire and release the store's `RLock` so read-modify-write sequences stay atomic under the threaded dev server.
- Error handlers: `ApiError` -> `error_response(err.error_id, err.message)`; 404 and 405 -> `ERR_RESOURCE_NOT_FOUND`; 400 -> `ERR_INVALID_REQUEST`; generic `HTTPException` and `Exception` fallbacks (the latter prints a traceback to stderr and returns `ERR_INVALID_REQUEST`).
- `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True, use_reloader=False)`. No seeding anywhere — every collection in `db.Store.reset()` starts empty; the only non-default boot state is the logical clock default `2026-08-01T00:00:00.000Z`.

## Verification results

- 30 files, 3798 lines total (`app.py` 106, 11 route modules 1812, 10 service modules 1229, 5 core modules 580, `start.sh` 10, `requirements.txt` 1). No SQLite, no disk writes, no `/tmp` cache.
- `python3 -m py_compile` on every `.py`: all compiled. `bash -n start.sh`: clean.
- Booted `PORT=18963 bash start.sh`, confirmed a single listener, ran a 40-call end-to-end flow, then killed only that pid (port confirmed free afterwards; no broad pkill used).
- The flow — practice -> permit -> inspection + result -> 4 drills -> 4 staff -> patient -> block -> case -> hold-block -> evaluation -> sign -> day-of-verification -> confirm -> implant lot -> reservation -> auto-size -> consume -> release -> start-recovery -> complete -> benefit determination -> submit -> payer-response -> adverse event -> morbidity review OPEN/SIGN_OFF -> close -> imaging study -> compliance sweep -> compliance summary — returned the expected status on **every** call, with zero tracebacks in the server log.
- Envelope/pagination/RBAC spot checks pass: unknown role -> 401, unpermitted role -> 403, `limit=0` -> 422 `ERR_INVALID_FIELD_VALUE`, unrouted path -> 404 `ERR_RESOURCE_NOT_FOUND`, list `meta` carries `limit`/`offset`/`total_count`/`has_more`, `api_request_id` is `req_` + 20 uppercase alphanumerics, timestamps have 3 fractional digits with `Z`.

Two initially-surprising 409s during smoke testing turned out to be correct enforcement, not bugs: `confirm` returned `ERR_STAFFING_RATIO_UNMET` because the surgeon had no `acls_expires_on` (required for MODERATE/DEEP), and `complete` returned `ERR_INVALID_STATE_TRANSITION` while an auto-sized reservation was still `HELD` (PRD line 242 requires inventory reconciliation first). Both cleared once the fixtures were corrected.

No sibling task directories, `test_helpers/`, `test_suite/`, or the two SCAFFOLD design files were read at any point.

## Step 7: Run tests and iterate — 2026-09-03T23:12:00.000Z

Orchestrator verification (per the known Step 7 failure mode of claiming a clean sweep with no artifacts): all 8 `workspace/implementation/results.$i.json` files exist (each ~36 KB, all timestamped 23:09) and each independently parses to `passed=113 total=113 failed=0`. The green claim is verified, not taken on trust.

Subagent summary (verbatim):

Clean sweep confirmed.

## Summary

**Iterations run:** 2. Sweep 1: 93/113 in all 8 rounds, 20 failures, identical set every round (fully deterministic — no flakiness, so no load-induced false positives to discount). Sweep 2: **113/113 in all 8 rounds.**

**Tests deleted:** none. All 20 failures traced to verbatim-PRD-covered rules; every one was either a real implementation defect or a test artifact that mis-expressed the PRD. No assertion was weakened, no skip/xfail added, no exact `error_id` downgraded.

**Fixes applied to `implementation/`**
- `services/inventory.py` -> `hold_pricing()`: stamp the tiered `restocking_fee_cents` at reservation creation instead of `0`. PRD §3.7 says "Pricing is pinned at the moment a reservation is created" and creation "computes all four money fields"; the fee was only being computed later on the RELEASED branch. **This single fix cleared 8 of the 20 failures** (across test_03, test_07, test_08, test_09, test_10, test_17). The RELEASED / SHORTED / quarantine-waiver branches already restated the field correctly and were left alone.

**Fixes applied to `test_helpers/`**
- `fixtures.py` -> new `assert_instant_equals()`: compares derived instants by the moment they denote. PRD mandates three-fractional-digit rendering only for `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.4) — it is silent on `issued_at`, `expires_at`, `remediation_deadline_at`, `reporting_deadline_at`. Raw-string equality was testing a PRD-undetermined spelling; the deadline *arithmetic* it was really asserting is fully preserved.
- `fixtures.py` -> `draft_case()`: added an overridable `primary_surgeon_id` (was hardcoded to `env["surgeon"]["id"]`, so passing it via `**overrides` raised `TypeError: got multiple values`). PRD's `ERR_BLOCK_SURGEON_MISMATCH` rule can only be exercised with a second surgeon on the roster. Cleared 2 failures.

**Fixes applied to `test_suite/`**
- `test_04` (x5 sites), `test_05` (x2), `test_07` (x1), `test_08` (x1): switched the 10 derived-instant assertions to `assert_instant_equals`. Cleared 6 failures.
- `test_07_boundary_precision.py` -> `test_one_minute_short_of_the_solids_floor_is_refused`: asserted `final_risk_score is None` after a rejected verification, contradicting PRD §3.5 — "recomputed by the final variant **before** any gate is evaluated, so the published score reflects reality even on a rejected attempt." Corrected to the PRD-derived `38.0` / `ELEVATED` (23.0 core + 15-point sub-480 solids penalty), which the neighbouring test's own docstring already named.
- `test_12` (x2), `test_13` (x1): setup called `set_clock("2026-06-05...")`, earlier than the mandatory `2026-08-01T00:00:00Z` boot default, so the monotonic clock correctly returned `ERR_CLOCK_MONOTONIC_VIOLATION` (§2.5). Moved to `2026-08-05`; every assertion in those tests is anchored to `acquired_at` (retention is explicitly clock-independent), so no expected value changed.

**Notable:** the ratio of test-artifact bugs to implementation bugs was 12:8, and the triage hint held — the `draft_case` and clock-default issues were upstream fixture faults masquerading as independent endpoint failures.

## Step 8: Finalize PRD — 2026-09-03T23:20:00.000Z

Orchestrator verification: `PRD_FINALIZED.md` exists, is 433 lines like `PRD.md`, and is NOT byte-identical to it — `diff` shows 8 changed lines (4 in-place sentence revisions), so the pass genuinely ran. Step 8 was not skipped because Step 7 applied 1 implementation fix plus test_helpers/test_suite fixes.

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with four minimal patches.

## Line counts
- `PRD.md`: 433 lines / 15,583 words
- `PRD_FINALIZED.md`: 433 lines / 15,841 words -> line delta 0.0%, word delta +1.66% (4 in-place sentence edits, no new sections/lines)

## Changes
- **§2.4 — insert** — pinned instant *rendering*: every server-derived instant (`issued_at`, `expires_at`, `remediation_deadline_at`, `outcome_recorded_at`, `signed_at`, `verified_at`, `recovery_started_at`, `reported_at`, `reporting_deadline_at`, `retention_until`, `swept_at`, `current_utc`/`previous_utc`) uses the same UTC-normalised three-fractional-digit form as `created_at`, while a caller-supplied instant retained on a row is echoed byte-for-byte and never re-rendered — `timeutil.py:62` (`fmt_dt`), `timeutil.py:1-6`, `db.py:59/66/68`, `validation.py:v_instant`, `services/permit.py:19-26`, `routes/events.py:38-40`, `services/imaging.py:21-26`, `routes/permits.py:183`, `routes/evaluations.py:121/181`, `routes/cases.py:297`, `services/sweep.py:103`.
- **§2.5 — revise** — the boot clock reads `2026-08-01T00:00:00Z` but is *reported* as `2026-08-01T00:00:00.000Z` — `db.py:12` (`CLOCK_DEFAULT`), `routes/ops.py:27-29`.
- **§3.5 (verification) — insert** — a CLEAR verification refused by one of the three clinical gates still persists the recomputed `final_risk_score`, the final-derived `risk_band`, both fasting instants, `escort_confirmed`/`escort_name`, and both `npo_*_minutes`, and refreshes `updated_at`/`version`, while `status` stays `SIGNED`, `verified_at` stays null and the case is untouched; the three access conditions instead write nothing — `routes/evaluations.py:145-178`.
- **§3.5 (band) — revise** — `risk_band` comes from `final_risk_score` from the moment the final variant has run at day-of verification (including a refused verification), not "once the evaluation is `VERIFIED`" — `services/risk.py:69-76` vs `services/risk.py:48-54`.

**No PRD edit** for two Step-7 items: the `hold_pricing()` restocking-fee fix (PRD §3.7 already pins "pricing is pinned at creation" + "computes all four money fields" + the tier formula, and `services/inventory.py:66-77` now matches verbatim), and the `draft_case()` fixture `TypeError` / clock-default fixture faults (pure test-helper bugs; `ERR_BLOCK_SURGEON_MISMATCH` order in `routes/cases.py:177-194` and the boot clock are already verbatim-PRD).

## Per-edit pre-edit search log
1. **§2.4 rendering.** (a) Subject: how every instant field is serialised. (b) Enumerated: grep of `fmt_dt|clock_str()|current_utc` across all of `implementation/` (13 sites), grep of `v_instant|parse_date(` across `routes/` + `services/` (all caller-instant sites), plus a key-name census of every `"*_at"/"*_on"/"*_date"/"*_utc"` literal to confirm no server-derived instant escapes `fmt_dt`/`db.current_utc`; read `timeutil.fmt_dt`, `db.new_record/touch/set_clock`, `validation.v_instant`, `routes/directory.py:15-35`, `routes/events.py:25-62`, `services/imaging.py`, `services/permit.py`. (c) Adjustment: scoped the verbatim-echo claim to instants "supplied by the caller **and retained on a row**", because `notified_at` (`routes/events.py:131`) is validated but never persisted; and listed `current_utc`/`previous_utc` on the server-rendered side, since the clock normalises caller input through `fmt_dt`.
2. **§2.5 boot clock.** (a) Subject: the startup clock value and its spelling. (b) Enumerated: `db.py:12` `CLOCK_DEFAULT`, `db.clock_str/clock_dt/set_clock`, `routes/ops.py:17-29` (monotonic compare uses parsed moments, so the `.000` spelling never affects the `ERR_CLOCK_MONOTONIC_VIOLATION` test), and `db.new_record` which copies `current_utc` into `created_at`/`updated_at`. (c) Adjustment: kept the canonical moment sentence intact and added the rendering as a parenthetical, so the monotonic and equality rules that follow are unchanged.
3. **§3.5 rejected-attempt persistence.** (a) Subject: what a day-of verification writes before/while failing. (b) Enumerated: `routes/evaluations.py:129-185` in full (access conditions at 145-151 raise pre-mutation; field writes at 156-161; `apply_final` at 163; the `except ApiError: touch(evaluation); raise` at 175-178; the success path at 180-184), `services/risk.py:57-76`, plus grep for every writer of `risk_band`/`final_risk_score`/`npo_*`/`escort_*` (only `create_evaluation`, `sign_evaluation`, `verify_evaluation`; no cascade/cancel rescoring, consistent with the existing "never rescored" sentence). (c) Adjustment: scoped persistence to "one of the three clinical gates below" and added the explicit contrast that the access conditions write nothing, so the sentence cannot be read as claiming a segregation/state failure also mutates the row.
4. **§3.5 band source.** (a) Subject: which score `risk_band` is derived from and when. (b) Enumerated: `services/risk.apply_provisional` (callsites `routes/evaluations.py:71` create, `:120` sign) and `services/risk.apply_final` (single callsite `:163`), `band_for` floors vs `services/domain` constants, and the confirm-side reader (`routes/evaluations.py:173` only) to confirm nothing else consumes `risk_band` in a way the new wording would contradict. (c) Adjustment: used "from the moment the final variant has run at day-of verification, including a verification a clinical gate then refused" rather than tying it to `VERIFIED` status, and left the `SUPERSEDED`/`VOIDED` never-rescored sentence untouched since no code path rescores those.

## Step 9: Complete PRD — 2026-09-03T23:52:00.000Z

Orchestrator decision (recorded per AUTONOMY clause): Step 9 was run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md` rather than one whole-implementation scan, because a single-shot scan of a 30-file / 3798-line implementation reliably degenerates into a byte-identical no-op copy. Pass A took the core/envelope/validation modules plus practices, permits, inspections, drills, directory, ops/clock/sweep, cascade and domain; pass B took blocks, cases, evaluations, scheduling and risk; pass C took benefits, implants, events, imaging and their services, and additionally owned the final integrity check. Pass A performed the `cp` from `PRD_FINALIZED.md`; B and C edited that same file in place.

Orchestrator verification: `PRD_COMPLETED.md` is 433 lines / 132,951 chars (from `PRD_FINALIZED.md` 433 lines / 117,098 chars, +15,853 chars); `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md`; `diff` shows 49 changed lines; §4 still carries 65 endpoint rows and §5 still carries all 40 error ids; the file ends on the final §5 table row (`ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED | 409`), a real section boundary. Also confirmed no `.py` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` was modified after the 23:09 green sweep, so the verified 8/8 x 113/113 result still describes the artifacts on disk.

Aggregate across the three passes: **48 ambiguity-pins, 8 mismatch-revisions, 0 new sections, 0 new lines** (every edit in-paragraph).

### Pass A summary (verbatim)

Pass A complete.

- `PRD_FINALIZED.md`: 433 lines / 117,098 chars -> `PRD_COMPLETED.md`: 433 lines / 121,332 chars (**+4,234 chars**, 17 lines revised in place, no new paragraphs or sections).
- **Confirmed not byte-identical** (`cmp` reports DIFFERENT; structure intact — 25 headings, error table tail unchanged).
- Counts: **17 ambiguity-pins, 0 mismatch-revisions** (impl never contradicted an existing PRD claim in my partition; every gap was silence).

Changes:
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + twenty random uppercase-alphanumerics; `api_request_timestamp` is read off the host's **real wall clock**, not the logical clock — `response.py:19,25`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_FIELD_VALUE`; empty string = omission; out-of-enum filter value -> same code; unpublished query params ignored — `validation.py:145-181`
- §2.3 — insert — ambiguity — `created_at` ties (common, since it comes off the logical clock) break by row-creation order — `db.py:85-87`
- §2.6 (4th check) — insert — ambiguity — body must be a JSON object; explicit `null` on a required field = absence; `null` on an optional field takes the default; absent/empty body = `{}` — `validation.py:20-40`
- §2.6 inventory — insert — ambiguity — patient `full_name` is 1–160 chars (staff is 1–120); the three inspection deficiency counts are required integers >= 0 — `routes/directory.py:65`, `routes/permits.py:161-163`
- §2.9 — insert — ambiguity — a body foreign key must be a non-empty string, so a blank id fails at priority five with `ERR_INVALID_FIELD_VALUE` before any lookup — `validation.py:119-125`
- §2.10 — insert — ambiguity — **the practice row is the exception to per-hop version counting**: `updated_at`/`version` advance at most once per request however many cascade hops write to it — `services/practice.py:14-23`
- §3.1 — insert — ambiguity — compliance-summary shape with no open permit: three permit fields null, both drill arrays empty, ratio 0.0, `drill_compliant` false — `services/practice.py:111-129`
- §3.1 — insert — ambiguity — `age_years` never negative (future `date_of_birth` accepted -> 0) and projected per read, so a clock advance changes it without touching `updated_at`/`version` — `services/risk.py:12-17`, `routes/helpers.py:15-18`
- §3.2 — insert — ambiguity — `required_drill_types` array order is the cumulative order, and `covered_drill_types` uses that same order (not rehearsal order) — `services/domain.py:54-60`, `services/practice.py:44-63`
- §3.2 — insert — ambiguity — `participant_staff_ids` are resolved **and** scope-checked one entry at a time in supplied order — `routes/permits.py:251-253`
- §3.2 — insert — ambiguity — both inspection-scheduling refusals are `ERR_INVALID_STATE_TRANSITION` (409), permit-status test before the open-inspection test — `routes/permits.py:111-115`
- §3.2 — insert — ambiguity — both result-posting refusals are `ERR_INVALID_STATE_TRANSITION` (409), status test before the clock test — `routes/permits.py:165-168`
- §3.2 — insert — ambiguity — `expires_at` = `issued_at` + 24 calendar months keeps time-of-day/day-of-month, clamping to month end — `timeutil.py:81-92`, `services/permit.py:16-22`
- §3.2 — insert — ambiguity — **every other outcome/permit-status pairing is inert on the permit** — `routes/permits.py:197-222`
- §3.10 — insert — ambiguity — unknown sweep `practice_id` -> `ERR_REFERENCED_ENTITY_NOT_FOUND` (404) — `routes/ops.py:36-38`
- §3.10 — insert — ambiguity — only blocks still in `RESERVED` are sweep candidates — `services/sweep.py:76-77`

Verified as already-pinned: clock default and monotonicity; envelope/pagination `has_more`; immutable-row shape; drill window and 0.75 inclusive floor; inspection score `max(0, 100-2m-7M-25c)` and its two-test branch; all issued/probation/revoked/applied branches; remediation's three ordered gates; privilege map and both cascade shapes incl. "no un-cascade on reinstatement"; sweep expiry-before-drill ordering, `DRILL_LAPSE`, block release branches and the nine response fields; all 40 error codes/statuses; §4 role lists and 201-on-create.

### Pass B summary (verbatim)

Pass B complete. All edits were inline; the file is still 433 lines.

- **PRD_COMPLETED.md before:** 433 lines / 121,332 chars -> **after:** 433 lines / 126,182 chars
- **Ambiguity-pins:** 12 - **Mismatch-revisions:** 6 (17 `Edit` calls total, incl. one wording tightening)

Changes:
- §3.3 — revise — mismatch — block release's `release_note` is described as "for the record", but impl accepts it without type-checking and never persists it — `routes/blocks.py:84`
- §3.3 — insert — ambiguity — a `surgeon_id` resolving to an in-practice staff member of the wrong `role_type` answers `ERR_INVALID_FIELD_VALUE` (422), tested after FK resolution and the scope check — `routes/blocks.py:38`
- §3.4 — insert — ambiguity — same rule/ordering pinned for a case's `primary_surgeon_id` — `routes/cases.py:98`
- §3.4 — revise — mismatch — "leaving `monitor_staff_id` null is legal only for `LOCAL_ONLY`" -> drafting never rejects a null monitor at any level (and never checks the monitor's `role_type`); enforcement is the confirmation staffing matrix — `routes/cases.py:74,86` + `services/scheduling.py:122`
- §3.4 — insert — ambiguity — a drafting-time `block_id` is resolved and scope-checked but inert — `routes/cases.py:87,95`
- §3.4 — insert — ambiguity — `prerequisite_case_id` at drafting is resolved but deliberately **not** practice-scope-checked — `routes/cases.py:88` vs `routes/cases.py:348`
- §3.4 — revise — mismatch — `referring_provider_npi` is a 1-to-32-character string whose digit count is not validated — `routes/cases.py:77`
- §3.4 — insert — ambiguity — re-point's `prerequisite_case_id` is mandatory and its tests run FK -> scope -> state -> cycle — `routes/cases.py:345-353`
- §3.4 — insert — ambiguity — `acknowledged_by_npi` is a required 1–32-char string that is validated but neither persisted nor compared to `referring_provider_npi` — `routes/cases.py:331-332`
- §3.4 — revise — ambiguity — hold-block gate three split into three ordered sub-tests with codes — `routes/cases.py:177-187`
- §3.5 — insert — ambiguity — evaluator `role_type` violation is `ERR_INVALID_FIELD_VALUE` (422) and precedes the `expected_case_version` comparison — `routes/evaluations.py:43-47`
- §3.5 — insert — ambiguity — the `clearance_status` reset on evaluation creation is conditional on something actually being superseded — `routes/evaluations.py:74-84`
- §3.5 — revise — mismatch — signing's precondition order is actor-identity **first**, then `DRAFT`, then parent-case-terminal — `routes/evaluations.py:113-118`
- §3.5 — revise — mismatch — signing sets the case's `clearance_status` to `EVALUATED` unconditionally — `routes/evaluations.py:124`
- §3.5 — revise — mismatch — day-of verification's three access conditions are ordered identity -> `SIGNED` -> parent-case-terminal — `routes/evaluations.py:145-151`
- §3.5 — insert — ambiguity — `npo_*_minutes` are floored and unclamped — `timeutil.py:95-98`, `services/risk.py:60`
- §3.6 — insert — ambiguity — a `LOCAL_ONLY` case skips the drill-compliance gate; the recomputed ratio is persisted but confirmation never advances the permit's `updated_at`/`version` — `routes/cases.py:223-227`, `services/practice.py:73-76`
- §3.6 — insert — ambiguity — start-recovery ordering: actor check, then state, then clock — `routes/cases.py:290-295`
- §3.6 — insert — ambiguity — complete's three `ERR_INVALID_STATE_TRANSITION` gates in order behind the actor check — `routes/cases.py:307-317`
- §3.6 — insert — ambiguity — cancellation hops two-to-four fire only when a reservation was actually released — `routes/cases.py:264-277`

Verified already-pinned: block ledger identity and both release branches; case drafting derivations and the eight list filters; hold-block gate order and turnover buffer semantics; all eleven confirmation gates incl. stale-block 412, privilege/permit-rank tables, the five staffing steps, monitor overlap, and peak-concurrency recovery projection; risk scoring formulas, bands, the provisional/final split, and the `DEFER` branch.

### Pass C summary (verbatim)

Pass C complete.

- lines 433 -> 433; chars 126,182 -> 132,951.
- **21 changes: 19 ambiguity-pins, 2 mismatch-revisions.** Changed lines are disjoint from A/B's.

Changes:
- §3.7 — insert — ambiguity — `manufacturer_code` 1–32 chars, `catalog_reference` 1–64, and `expiry_date` never tested against the logical clock — routes/implants.py:33-39, 155
- §3.7 — insert — ambiguity — the boolean `is_consignment` filter accepts `true`/`false`/`1`/`0` in any case — routes/implants.py:75, validation.py:184
- §3.7 — insert — ambiguity — `quarantine_reason` validated but never persisted — routes/implants.py:89-90
- §3.7 — insert — ambiguity — quarantine admitted only from `AVAILABLE` — routes/implants.py:92
- §3.7 — insert — ambiguity — a quarantined lot's `available_quantity` stays 0 — services/inventory.py:48-51
- §3.7 — insert — ambiguity — quarantine advances `version` by 1 + holds released — routes/implants.py:96-101
- §3.7 — insert — ambiguity — auto-size requested dimensions must exceed 0 — routes/implants.py:167-168
- §3.7 — **revise — mismatch** — dimensions compared as exact decimals with no prior rounding — services/inventory.py:140-141
- §3.7 — revise — ambiguity — when `ERR_LOT_UNAVAILABLE` fires on the auto-size path — services/inventory.py:158-169
- §3.7 — **revise — mismatch** — candidate ordering is not four-key: `created_at` ties break by row-creation order — services/inventory.py:170-171
- §3.7 — insert — ambiguity — neither reservation path gates on the case's `scheduling_status` — routes/implants.py:145, 165
- §3.7 — insert — ambiguity — the credit-limit test is strict from stored `consignment_committed_cents` — services/inventory.py:85-88
- §3.7 — insert — ambiguity — the three consume gates and their differing codes — routes/implants.py:208-213
- §3.8 — insert — ambiguity — full `service_lines` error split (422 vs 400) and structural-pass-first ordering — routes/benefits.py:20-50
- §3.8 — insert — ambiguity — opening a determination is not gated on `scheduling_status` — routes/benefits.py:60
- §3.8 — insert — ambiguity — a line's `benefit_class` is stored/echoed but never read by the allocation — services/benefit.py:35-69
- §3.8 — insert — ambiguity — `pend_reason`/`denial_reason` conditional requirement evaluated *before* the `SUBMITTED` state test — routes/benefits.py:131-161
- §3.9 — insert — ambiguity — a future `occurred_at` -> `ERR_INVALID_FIELD_VALUE` before `case_id` resolves; `narrative` 1–2000 chars — routes/events.py:31-35
- §3.9 — insert — ambiguity — sentinel enforcement inert with no open permit or a permit in `APPLIED`/`INSPECTION_PENDING`/`SUSPENDED` — services/permit.py:94-103
- §3.9 — revise — ambiguity — morbidity review orderings; SIGN_OFF tests actor identity before state — routes/events.py:97-121
- §3.10 — insert — ambiguity — `notified_at` and `notification_reference` validated then discarded — routes/events.py:130-140
- §3.10 — insert — ambiguity — a future `acquired_at` -> `ERR_INVALID_FIELD_VALUE` before either FK resolves — routes/imaging.py:28-33
- §3.10 — insert — ambiguity — the CBCT pairing test runs after FK resolution and the scope check — routes/imaging.py:33-39
- §3.10 — insert — ambiguity — a `date_of_birth` after `acquired_at` counts as an under-18 acquisition — services/imaging.py:22-26

Verified already-pinned: restocking tiers and half-up cent rounding; 20% consignment credit; liability by status incl. `SHORTED`; the four money fields at creation; quarantine's fee waiver; the explicit path's four-gate order; expiry-vs-`planned_start`; routing table and `primary_payer`; per-line round-before-sum in both waterfalls; `MEDICAL_PRIMARY` leaving dental at 0; snapshot freeze/refresh; submission gates and `submission_count`; `APPROVED` drawdown floored at 0; `DENIED` zeroing; the conserved money identity; the 24h/72h/7d/30d deadline table and `late_report`; `open_adverse_event_count` maintenance; the one-shot notification flag; the modality/justification matrix and dose reference levels; study immutability; retention as max(acquisition floor, majority+7).

Final-pass integrity: 433 lines; §4 has 65 endpoint rows, §5 has 40 error rows; all 28 headings byte-identical to PRD_FINALIZED; ends at the real §5 boundary; `cmp` confirms not byte-identical to PRD_FINALIZED.md.

--- PIPELINE COMPLETE: Step 9 wrote workspace/PRD_COMPLETED.md ---
