# Worklog — task_2579_utility_scale_solar_construction_commissioning

## Step 1: Create task directory — 2026-09-03T15:11:26.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2579_utility_scale_solar_construction_commissioning` and its `workspace/` subdirectory. Index 2579 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T16:27:29.000Z

All three scaffold artifacts are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2579_utility_scale_solar_construction_commissioning/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | **1913** | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **1413** | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **3575** | `scaffold_corner_design` only |

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2579_utility_scale_solar_construction_commissioning/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2579_utility_scale_solar_construction_commissioning/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2579_utility_scale_solar_construction_commissioning/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  843

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold shape

§1.0–§1.7: 14 entities, 12 state machines, 2 OCC concurrency rules, 18 calculations, 56 validations on a 29-level priority ladder, 64 endpoints, 56 errors, 8 roles. Profile: primary `compliance_audit` / secondary `workflow_orchestration`; layers `cascading_side_effects`, `dual_variant_calculation`, `derived_field_reconciliation`, `optimistic_concurrency`; topology `hybrid`, shape `parallel`, `role_model: segregation_of_duties`, consistency `immediate`.

§1.8: 18 instances, exactly 2 per each of the nine §0.5 rules.

§1.9: 69 instances (53 with full `test_recipe`, 16 `excluded_because` stubs) across all nine sections — entities 12, state_machines 15, calculations 13, validations 9, endpoints 6, errors 4, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1. `bulk_action` is the only Table-5 row deliberately unrepresented, since the API declares no bulk endpoints.

## Work done this session

- Appended `cross_cutting_complexity_layers`: a full both-OCC-rules instance (`stale_parent_versions_are_rejected_on_both_occ_write_endpoints`, asserting each rule returns its own 412 code and that refused writes bump nothing), a full `derived_field_reconciliation` instance that drives `blocks_mc_ready_count` up 0→1→2 then **back down to 1** via a failing re-test (proving recomputation, not latching), plus stubs for `cascading_side_effects` and `dual_variant_calculation` citing their §1.8 counterparts.
- Appended `consistency_model` (`immediate`): asserts the receipt response already carries `damage_ratio`/`accepted_unit_qty`/ACCEPTED and that sibling reads reconcile with no settling step.
- Closed a coverage gap found by audit: 10 declared nested collection reads were never called by any instance. Added one `standard_crud` instance covering all 10 with two-children-in-different-states setups and per-filter literals.

Final audits: all 56 error codes triggerable, all 64 endpoints called, all 8 roles exercised, 87 instance names unique across both design files, every stub cites a real §1.8 instance (never another corner instance), and no instance has both `test_recipe` and `excluded_because`. Sibling tasks were never read — the scaffold came only from the scenario text and the skill spec.

One earlier-session fix worth flagging: `RAIN_TRIGGER_INCHES`, `RAIN_BLACKOUT_HOURS` and `MIN_COMPACTION_PCT` were referenced in prose but declared nowhere, so a new `site_condition_gates` calculation was added to SCAFFOLD.yaml with values consistent with the already-written blackout difficulty instance.

## Step 3: Copy shared files — 2026-09-03T16:27:29.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T16:44:00.000Z

The PRD is complete and all corrections are applied.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2579_utility_scale_solar_construction_commissioning/workspace/PRD.md` — **502 lines**, ending at a real section boundary: the completed §5 Error Code Catalogue table, final row `| \`ERR_CHANGE_ORDER_CAP_EXCEEDED\` | 422 |`. No mid-sentence truncation. Written as 1 `Write` + 5 `cat >> … <<'PRDEOF'` heredoc appends, per instruction.

**Final fixes applied this pass**
- Replaced 3 Unicode minus signs (U+2212) with ASCII hyphens so `-0.0028`, `-0.0035` and `-10` match the scaffold constants literally. `U+2212` count is now 0.
- Added the third `permit_status` enum value in §3.2: `TERMINATED` is now named alongside `ACTIVE` and `SUSPENDED`, documented as coverage withdrawn outright and not reachable through any operation in this specification.
- Added `substation_id` in §3.6 as a named field of the outage-window record (it previously appeared only inside §4 path templates, which do not satisfy Contract 1 since §4 paths are the path column, not a field mention).

**Hard Contract 1 — Field-Name Coverage: PASS.** 163 distinct scaffold identifiers (entity `fields`, `request_body`, `query_params`, `path_params`) checked against backticked tokens outside fenced code blocks. **0 missing.**

**Hard Contract 2 — Rule Coverage: PASS.** All 56 error ids present (the 57th regex hit, `ERR_XXX`, is the scaffold's envelope illustration placeholder, not a real error). All 8 role names present in backticks. All 83 enum values from entity constraints present. All 64 endpoint paths present. 29-step validation precedence ladder rendered in §2.7 naming every error id in priority order; both OCC rules (`expected_yard_zone_version`/`ERR_STALE_YARD_ZONE_VERSION`, `expected_project_version`/`ERR_STALE_PROJECT_VERSION`, both 412) in §2.8; all 10 state machines, 17 calculations and endpoint side effects narrated in §3. Every numeric calculation constant is literally present — the two regex "misses" are false positives: `0.6900` is an `e.g.` illustration inside a field description, and `71.7` is a fragment of the section reference `§1.7`.

**Hard Contract 3 — §3 Path Purity: PASS.** 1114 backticked tokens scanned across §3.1–§3.9: **0** `/`-leading tokens, **0** bare HTTP methods, **0** method+path combos.

**Other verifications**
- §2.2 is byte-identical to `section-2.2-response-structure.md` (diff shows only the trailing blank separator line before §2.3).
- §4 table has exactly 64 rows and 4 columns; §5 table has exactly 56 rows and 2 columns.
- No forbidden or fuzzy wording ("approximately", "roughly", "conservatively", "pseudocode", "etc.") and no occurrence of "difficulty"/"Difficulty" anywhere in the file — the document reads as a normal implementer-facing PRD.
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.
- No report/summary `.md` files were created; the contract reports exist only in this message.

**Orchestrator truncation check (per pipeline directive):** verified independently — `wc -l` = 502; `tail -25` shows the error table completing normally; `grep '^#'` shows all sections §1 through §5 present with §5 last. Not truncated.

## Step 5: Generate unit tests — 2026-09-03T17:34:00.000Z

All nine queue A files are done; the full seventeen-file suite verifies clean.

## Work completed this session

Wrote the last three queue A files (`test_07`–`test_09`), each translating both instances of its `rule_id` from `SCAFFOLD_DIFFICULTY_DESIGN.yaml`:

- `.../test_suite/test_07_cross_entity_state_dependency.py` — 303 lines, 8 tests. Finalization gated on `ERR_SUBSTATION_NOT_ENERGIZED` (422) then granted after the advance to `ENERGIZED`, asserting `energizing_outage_window_id` names the consumed window and the identical call now reports 76.50 / FAILED against 98.00; and the pile drive gated on `ERR_GRADING_AREA_NOT_ACCEPTED` (409) with every measurement still null, then admitted to `ACCEPTED` / `PILES_COMPLETE` / `mc_ready` false after owner acceptance.
- `.../test_suite/test_08_resource_temporal_overlap.py` — 318 lines, 10 tests. Half-open laydown windows: 60+50 refused, the abutting 30-pallet window admitted, the 10-pallet window admitted at exactly 100, one more pallet refused, and only admitted reservations moving the zone version. Closed outage windows: the 90-minute gap and the touching endpoint both `ERR_OUTAGE_WINDOW_CONFLICT` (409), 06:01 clearing the 120-minute buffer, `DENY` freeing the feeder for an identical re-request with a new id, and the listing holding exactly 3 windows with the substation still `SITE_CIVIL`.
- `.../test_suite/test_09_compensating_invariant.py` — 297 lines, 9 tests. Reserve→cancel restoring 0/100 with the zone version advanced by exactly 2 and the freed window taking a 100-pallet shipment; post→void restoring the week to 8.00/8.00/0.00 with `entry_count` 1, `apprentice_pct` recomputed to 100.00 rather than the stale 44.44, and the project rollups back to 8.00/8.00.

## Final verification

- `python3 /tmp/verify_quotes.py` over all 17 files: **0 quote/tag problems** — every test docstring carries exactly one `Design:` line and at least one PRD citation that is a verbatim (whitespace-normalized) substring of `workspace/PRD.md`.
- Independent tag resolution against both yaml files: **0 dangling tags**; 71 distinct tags = **18 Difficulty + 53 Corner**.
- `pyflakes`: clean on all 17 test files and all helpers (only the usual re-export warnings on `test_helpers/__init__.py`, which has an `__all__`).
- `pytest --collect-only`: **207 cases from 174 test functions** (the gap is parametrization in `test_11` and `test_16`).

## Coverage tally — zero skips

| Queue | Instances in yaml | Non-stub | Translated | Skipped |
|---|---|---|---|---|
| A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`) | 18 | 18 (no `excluded_because:`) | **18** | 0 |
| B (`SCAFFOLD_CORNER_DESIGN.yaml`) | 69 | 53 (16 stubs) | **53** | 0 (16 stubs correctly untranslated) |

## Per-file line counts

Queue A (73 functions / 2603 lines): test_01 341·8, test_02 239·7, test_03 262·8, test_04 298·8, test_05 246·7, test_06 291·8, test_07 303·8, test_08 318·10, test_09 297·9.
Queue B (101 functions / 4517 lines): test_10 654·21, test_11 1017·37, test_12 527·6, test_13 453·7, test_14 630·5, test_15 575·13, test_16 375·7, test_17 286·5.
Infrastructure: `conftest.py` 150; `test_helpers/` 3134 lines across 9 modules (`fixtures.py` 800, `types.py` 513, `assertions.py` 461, `api_client.py` 450, `factories.py` 405, `api_errors.py` 151, `test_users.py` 147, `__init__.py` 113, `constants.py` 94).

## Notes for the caller

- One live helper bug was fixed earlier this session: `assert_page_meta` read `meta["total"]`, which `validate_paginated` never produces; it now requires `total_count`/`limit`/`offset` and accepts a `has_more` keyword. No test file depended on the old shape.
- Path rule honoured: both directories sit at the task root, nothing was written inside `workspace/` (it still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`), and `workspace/implementation/` was never read. `__pycache__` directories left by the collect-only run were removed.
- Three PRD-first deviations reported by queue B peers stand as accepted (an omitted pre-certification `ld_cap_cents == 0` assertion, a `WAIVE` that legally requires a prior closure submission, and an internally impossible nested-read fixture rebuilt as its legal 60/40 equivalent), plus a `circuits_tested_count` the PRD makes 0 rather than 1 in one rollup instance.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` confirmed at the task root; nothing was written under `workspace/`.

## Step 6: Generate implementation — 2026-09-03T17:34:00.000Z

Implementation complete and verified. Both smoke servers (ports 18579, 18580) were killed by their specific listening PIDs; no broad pkill was used, and no residual processes remain on either port.

## Deliverable
`.../workspace/implementation/`

| file | lines |
|---|---|
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| `app.py` | 67 |
| `errors.py` | 77 |
| `envelope.py` | 87 |
| `clock.py` | 111 |
| `store.py` | 115 |
| `validate.py` | 219 |
| `calc.py` | 523 |
| `routes/__init__.py` | 1 |
| `routes/common.py` | 38 |
| `routes/projects.py` | 276 |
| `routes/civil.py` | 230 |
| `routes/yard.py` | 177 |
| `routes/arrays.py` | 301 |
| `routes/grid.py` | 160 |
| `routes/commissioning.py` | 163 |
| `routes/punch.py` | 111 |
| `routes/payroll.py` | 181 |
| **total** | **2848** |

All 17 modules pass `ast.parse`. `import app` reports **64 wired endpoints** (63 spec endpoints + the `POST /_clock/set_current_utc` test hook). `__pycache__` removed; nothing but source on disk.

## Compliance with the hard constraints
- Storage is 14 module-level dicts in `store.py`. No SQLite, no file writes, no `/tmp` cache — cold boot on 18580 returned `{"data":[],...,"total_count":0}` for `GET /solar/projects`, proving zero seeding.
- `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s in the foreground, and installs flask only when the import fails (an unconditional `pip install` on every per-test reboot causes boot contention/flaky restarts).
- Inputs read were only `SKILL.md`, `workspace/INSTRUCTION.md`, `SCAFFOLD.yaml`, `workspace/PRD.md`. `test_helpers/` and `test_suite/` were never listed or read.

## Verification
Two end-to-end scripts both finished ALL GREEN, covering: earthwork conflict 409, pile refusal → block `HOLD` → remediation → `PILES_COMPLETE`, out-of-tolerance pile leaving the block version untouched, `ERR_STALE_YARD_ZONE_VERSION` 412, `ERR_STALE_PROJECT_VERSION` 412, half-open laydown windows (touching windows do not collide) plus pallet conservation across cancel and rejected-receipt paths, `damage_ratio` 0.02 → ACCEPTED / 0.10 → REJECTED, `expected_voc_v == 1386.00`, `mc_ready` → project READY, MC/punch/payroll `ERR_SEGREGATION_OF_DUTIES` 403, outage ±120-min buffer conflict 409, energization stamping `energizing_outage_window_id` and driving the window to EXECUTED, weather-corrected interval `1055.41` kW and `is_valid=false` → `corrected_kw_ac=null`, capacity 995.0 vs threshold 980.0 PASSED, PR 0.7308 PASSED, the readiness-loss cascade (failing string test → block REWORK → project BLOCKED → `AUTO_MC_READINESS_LOST` claim reversal → test `SUSPENDED`/`MC_READINESS_LOST`), test supersession to `VOID`/`SUPERSEDED_BY_NEW_TEST`, STRICT `ERR_BELOW_PREVAILING_WAGE` 422, void restoring week and project hour ledgers to zero, and the SC waterfall (`delay_days 31`, `ld_assessed 3100000`, `retainage 5000000`, `sc_payment_due 91900000`, FA `final_payment_cents 5000000`).

## PRD ambiguities and how I resolved them
1. **Duplicate natural keys** (`zone_code`, `area_code`, `block_code`, `circuit_code`, `substation_code`, duplicate `week_start_date`) have no dedicated error id in the 56-error catalog, so all collide to `ERR_INVALID_REQUEST` 400 (`routes/common.py:unique_check`).
2. **Which mutations bump `Project.version`.** The PRD names the optimistic-concurrency guard but not the exhaustive bump list. I bump unconditionally on structural/financial writes (grading-area create + acceptance, block create, punch-item create, commissioning-test create, labor-entry post/void, change order, compliance run, milestone claim/decision) and conditionally elsewhere via change detection over the derived tuples in `calc.sync_project`. Same split for Block via `calc.sync_block`; `force=True` is used only for mechanical-completion, where the snapshot is taken after a direct mutation.
3. **Test-creation OCC vs. its own bump.** `expected_project_version` is compared against the version *before* the create's own bump, otherwise no client could ever supply a satisfiable value.
4. **`settlement_summary.ld_cap_cents`** is one of the six waterfall figures specified to stay 0 until SC certification, so the computed cap is kept in a private `_ld_cap_cents` field (stripped by `envelope.dump`, which drops `_`-prefixed keys) and surfaced only by the settlement-summary endpoint after certification.
5. **Energizing outage-window selection** when several APPROVED BACKFEED windows contain the logical `now`: the PRD does not tie-break, so the earliest-created one wins and is driven to `EXECUTED`.
6. **Payroll ordering of the work-date check vs. the week-locked check.** Work-date membership is a request-shape violation, so it precedes `ERR_PAYROLL_WEEK_LOCKED`; conversely for void, `ERR_LABOR_ENTRY_ALREADY_VOIDED` precedes the week check since the entry is the addressed resource.
7. **Certifying an empty payroll week** has no dedicated error, so it returns `ERR_INVALID_REQUEST` 400.
8. **Rejected delivery receipt.** Accept/reject resolves inside the single receipt request (there is no separate decision endpoint); rejection zeroes `accepted_unit_qty`, releases the reserved pallets, and bumps the yard zone.
9. **Unmapped framework failures** (bad JSON, wrong method, unknown route) map to `ERR_INVALID_REQUEST` with Werkzeug's own status code; a truly unexpected exception yields `ERR_INTERNAL` 500.

**Orchestrator endpoint check:** an independent diff of PRD §4's 64 endpoint rows against Flask's registered `url_map` found 0 missing and no extras beyond Flask's built-in `/static/<path>`. All 64 declared endpoints are wired.

## Step 7: Run tests and iterate — 2026-09-03T18:15:00.000Z

Green sweep achieved.

## Summary

**Iterations run:** 2 (sweep 1 → diagnose/fix → sweep 2).

- Sweep 1: 205/207 in all 8 rounds; the union of failures was exactly 2 tests, identical and deterministic in every round (no flakiness, no load-induced timeouts, no `Terminated` reaping pattern).
- Sweep 2: **207/207 in all 8 rounds**, 0 failed / 0 errors / 0 skipped, ~369s per round.

**Tests deleted:** none. Both failures were partial-coverage cases (STEP 1c), not PRD silence on the underlying rule.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — new `assert_instant_equals(actual, expected, label)`: parses two ISO-8601 UTC strings (fractional digits optional, `Z` required) and asserts exact instant equality. Needed because the PRD fixes the spelling only for `created_at`/`updated_at`/`api_request_timestamp` ("ISO 8601 UTC timestamp with three fractional digits") and says nothing about the spelling of the domain instants it derives.
- `test_helpers/__init__.py` — re-exports the new helper alongside the other assertions.

**Fixes applied to `implementation/`:** none — no implementation change was warranted.

**Diagnosis detail (both failures, same root cause):**
- `test_05_priority_pair_validation_conflict.py::test_a_quarter_inch_storm_sets_a_forty_eight_hour_blackout` — asserted `rain_blackout_until == "2026-08-07T18:00:00Z"`; server returned `"2026-08-07T18:00:00.000Z"`.
- `test_07_cross_entity_state_dependency.py::test_energization_consumes_the_window_and_records_which_one` — asserted `energized_at == "2026-08-10T02:00:00Z"`; server returned `"2026-08-10T02:00:00.000Z"`.

PRD §3.2 states only that `rain_blackout_until` "is set to `occurred_at` advanced by 48 hours", and §3.6 that `energized_at` "is stamped with the current logical-clock instant" — the instant is uniquely derivable, the serialization spelling is not (a faithful reader may either echo the client/clock spelling or reuse the three-fractional-digit convention §2.4 mandates for `created_at`). The implementation's `.000Z` is the §2.4-consistent reading, so the over-specified part lived in the test. Per STEP 1c the covered assertion (exact instant) was kept and the uncovered assertion (exact character spelling) removed; the instant equality is still exact, so nothing was weakened. These were the only two raw timestamp-string comparisons in the whole 207-test suite — every other test already compared timestamps format-agnostically.

**Orchestrator artifact verification (per pipeline directive):** independently confirmed all 8 `results.{1..8}.json` exist (~64KB each, same mtime) and every one reports `passed=207, failed=0, total=207, errors=0, skipped=0`.

**Step 8 decision:** NOT skipped. The skip condition requires zero iterations and zero fixes of any kind; this run had 2 iterations and 2 test-artifact fixes that revealed a genuine PRD silence (serialization spelling of derived domain instants). Step 8 therefore runs with the above as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T17:59:05.000Z

Done.

## Line counts
- `PRD.md`: 502 lines
- `PRD_FINALIZED.md`: 504 lines (+2 lines, **+0.40%**)

## Changes (1)
- **§2.4 Resource Identity, Timestamps and Version Semantics** — *insert* — added one paragraph pinning the three-fractional-digit `...Z` ISO-8601 UTC spelling as the service's **single** serialization convention for *all* instant-valued fields (not just `created_at`/`updated_at`/`api_request_timestamp`), including clock-stamped instants, arithmetic-derived instants, and client-supplied instants (which are **normalized**, not echoed character-for-character); calendar-date fields carved out as `YYYY-MM-DD` — `implementation/clock.py:78-85` (`fmt_datetime`), `implementation/envelope.py:29-44` (`_val`/`dump`).

## Pre-edit search log

**Edit 1**
- **(a) Subject:** the wire spelling of every instant the server serializes (triggered by the two Step 7 sites: `rain_blackout_until` in §3.2, `energized_at` in §3.6, both returning `.000Z` where the tests expected `Z`).
- **(b) Impl paths enumerated:**
  - `grep -rn "fmt_datetime|isoformat|strftime"` across the whole impl → only 3 callsites, all funnelling into one formatter: `clock.py:78` `fmt_datetime` (`"%Y-%m-%dT%H:%M:%S." + "%03dZ"`), `envelope.py:22` (`api_request_timestamp`), `app.py:28` (`/_clock/set_current_utc` response).
  - `envelope.py:29-54` `_val`/`dump` — read fully: **all** `datetime` values in **any** entity go through `fmt_datetime`; `date` values (checked *after* `datetime`, so subclass ordering is correct) go through `isoformat()`; nested `dict`s recurse through `dump`, so `earthwork_windows` records are covered too; `_val` is used by `ok`, `created` and `collection`, so single-reads, creates and list rows are all identical.
  - `validate.py:88-97,160-165` — `dt()`/`dy()` coerce every client-supplied instant/date via `clock.parse_datetime`/`parse_date` into `datetime`/`date` objects, so nothing is ever stored as a raw client string and every echoed instant is re-rendered by the same formatter. `clock.py:33-60` `_DT_RE` confirmed to accept no-seconds, fractional and `±HH:MM` offset spellings.
  - Grepped every `*_at` / `*_start` / `*_end` / `*_until` assignment across `routes/*.py` and `store.py` to confirm the stored value is always `clock.now()`, `None`, or a parsed `data[...]` datetime — never a string: `civil.py:46,124-125,170,174`, `yard.py:62-64,89-91`, `arrays.py:101,137,149,232,298`, `grid.py:47,101,121-126,158`, `commissioning.py:27,54,61,92,107,161`, `payroll.py:24-41,179`, `projects.py:41,65`, `store.py:37-46`.
  - Ran the round-trip empirically: `2026-08-05T08:00Z` and `2026-08-05T10:00:00+02:00` both serialize to `2026-08-05T08:00:00.000Z`.
- **(c) Wording adjustments made:** (i) framed the rule as a *global* convention in §2.4 rather than adding two local notes at §3.2/§3.6, since the impl has exactly one formatter and a local note would falsely imply other fields are unconstrained; (ii) initially listed `driven_at` under "stamped from the logical clock" — `arrays.py:149` is `data["driven_at"] or clock.now()`, so it was re-listed as "the optional `driven_at`" under client-supplied inputs; (iii) said "three fractional digits" rather than claiming any rounding/truncation rule for sub-millisecond input, leaving that path deliberately under-determined; (iv) explicitly carved out `sc_deadline_date`/`week_start_date`/`work_date` so the new universal claim does not mis-describe the `date` branch of `_val`.

**Note on scope:** the `<step_7_diff>` contained exactly one PRD-silence item (both failures shared one root cause; no impl changes, no test deletions), so this is the only edit.

**Orchestrator verification:** `PRD_FINALIZED.md` exists at 504 lines and `diff` against `PRD.md` shows exactly the one §2.4 insertion described above — the file is not a byte-identical copy.

**Step 9 plan (orchestrator decision):** Step 9 will run as three sequential file-partitioned passes over `implementation/` rather than one agent scanning all 2848 lines, because a single-agent full scan of a 19-module implementation reliably under-covers and can return a byte-identical PRD_COMPLETED.md. Partition: pass A = global/infra + projects + civil; pass B = yard + arrays + grid; pass C = commissioning + punch + payroll + calc remainder. Passes are strictly sequential so each edits the same PRD_COMPLETED.md without write conflicts.

## Step 9: Complete PRD — 2026-09-03T18:35:00.000Z

Run as three sequential file-partitioned passes over `implementation/` (orchestrator decision recorded in the Step 8 entry). All three passes edited the single `workspace/PRD_COMPLETED.md` in place with the Edit tool; pass A created it from `PRD_FINALIZED.md`.

**Aggregate result:** `PRD_FINALIZED.md` 504 lines / 104,995 chars → `PRD_COMPLETED.md` 506 lines / 116,765 chars (**+2 lines, +11,770 chars**, 88 changed lines). **53 edits total: 47 ambiguity-pins, 6 mismatch-revisions.**

### Pass A — infra + §3.1 projects + §3.2 civil (app.py, envelope.py, errors.py, clock.py, store.py, validate.py, routes/common.py, routes/projects.py, routes/civil.py)

504 → 506 lines, +6,694 chars. 22 ambiguity-pins, 2 mismatch-revisions.

- §2.1 — revise — ambiguity — header rejection also covers a present-but-empty header; role match is exact/case-sensitive, whitespace not trimmed — `validate.py:24-27`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars — `envelope.py:12-16`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock — `envelope.py:22`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; empty-string value falls back to the default — `validate.py:174-191`
- §2.3 — revise — ambiguity — `created_at` ordering ties are broken by insertion order (critical, since the clock is frozen by default); same tie-break applies to the three domain orderings — `store.py:50-52`, `routes/payroll.py:59,124`
- §2.3 — insert — ambiguity — filters match by exact equality, an out-of-set filter value yields an empty page rather than an error, boolean filters accept `true/false/1/0` case-insensitively, unrecognized query params are ignored — `routes/common.py:16-19`, `validate.py:202-211`
- §2.4 — insert — ambiguity — an instant with no zone designator is read as UTC; `t` or a space is accepted as the date/time separator — `clock.py:33-60`
- §2.5 — insert — ambiguity — clock endpoint takes only `now`, returns 200 with `data` = `{"now": …}` — `app.py:22-28`
- §2.7 (step 3) — insert — ambiguity — integer-typed positions reject fractional numbers; numeric strings and booleans rejected where a number is declared; explicit `null` treated as absent — `validate.py:57-98,131-136`
- §2.7 — insert (new paragraph) — ambiguity — scoped-uniqueness collisions (`area_code`, `zone_code`, `block_code`, `substation_code`, `week_start_date`, `circuit_code`) report `ERR_INVALID_REQUEST`/400, evaluated after path + FK resolution and after the cross-project check — `routes/common.py:22-26`, `routes/civil.py:34-35`, `routes/arrays.py:30-33`
- §3.1 — revise — ambiguity — `guaranteed_performance_ratio`'s four decimals are a convention; only the strict 0–1 bounds are enforced — `routes/projects.py:43`
- §3.1 — revise — ambiguity — `amount_cents` has no sign constraint; no change-order resource is persisted and the response is the project — `routes/projects.py:139-148`
- §3.1 — revise — ambiguity — settlement-summary is a bare eleven-field object with no `id`/timestamps/`version` — `routes/projects.py:119-133`
- §3.1 — revise — **mismatch** — `ld_cap_cents` is frozen at SC certification (0 before it, unaffected by later change orders), not computed live — `routes/projects.py:123,253`, `calc.py:504`
- §3.2 — revise — ambiguity — `access_road_meters` is an integer in whole metres — `routes/civil.py:32`
- §3.2 — revise — ambiguity — `acreage_disturbed_delta` may be 0 — `routes/civil.py:84`
- §3.2 — revise — ambiguity — an `earthwork_windows` record carries exactly four keys; `crew_ref` is accepted but never persisted — `routes/civil.py:122-129`
- §3.2 — insert — ambiguity — an earthwork log persists no resource of its own, responds with the area, and never bumps the project's `version` — `routes/civil.py:135-139`
- §3.2 — insert — ambiguity — site-event `note` is not persisted; `rainfall_inches`/`deficiencies_found` conditionally required by event type, and supplying one on an ignoring type is accepted — `routes/civil.py:145-156`
- §3.2 — insert — ambiguity — a site event bumps `version`/`updated_at` only when it changes one of six area fields — `routes/civil.py:159-202`
- §3.9 — insert — ambiguity — a rejection omitting `reason` writes null into `last_milestone_rejection_reason`; a certification never touches that field — `routes/projects.py:239,258,273`
- §3.9 — insert — **mismatch** — the three final-acceptance-claim gates fire in §2.7 order (required test **before** open punch items), not in the order §3.9 lists them — `routes/projects.py:201-208`
- §4 preamble — insert — ambiguity — every non-creating POST returns the resource its own path addresses, and none persists an addressable resource — all `routes/*.py`
- §5 preamble — insert — ambiguity — a non-object body is 400 `ERR_INVALID_REQUEST`; an unmatched path/method is `ERR_INVALID_REQUEST` carrying the router's 404/405 — `app.py:50-54`, `validate.py:43-54`

Judged already-pinned: envelope/pagination shapes, serialization + rounding + id conventions, the 8-role/one-write-role auth model and ladder ordering, all §3.1 create fields and derived nulls, change-order cap against the base contract, §3.2 creation defaults, the per-activity status matrix, all five civil gates and their boundaries, append-only window history, permit hold/reinstatement, acceptance preconditions, and the §3.9 milestone ladder incl. the settlement waterfall and freeze.

### Pass B — §3.3–§3.6 yard/arrays/grid (routes/yard.py, routes/arrays.py, routes/grid.py + their calc.py helpers)

506 → 506 lines, +2,057 chars. 12 ambiguity-pins, 1 mismatch-revision.

- §3.3 — insert — ambiguity — reserving/receiving/cancelling a delivery never bumps the *project* `version` — `routes/yard.py:101-104,151-159,170-177`
- §3.3 — insert — ambiguity — `damaged_unit_qty > received_unit_qty` is a §2.7-step-3 `ERR_INVALID_REQUEST`, ahead of existence and `RESERVED` checks — `routes/yard.py:132-135`
- §3.3 — insert — ambiguity — a receipt omitting `inspection_note` leaves the reservation-time note in place — `routes/yard.py:144-145`
- §3.3 — insert — ambiguity — on the `ACCEPTED` receipt branch the zone ledger does not move and the zone's `version` is untouched — `routes/yard.py:148-159`
- §3.4 — insert — ambiguity — block creation bumps the project unconditionally, and a `READY` project loses readiness (claim auto-withdrawal + live-test suspension) in that same request — `routes/arrays.py:56`, `calc.py:257-296`
- §3.4 — insert — ambiguity — drive-result `actual_embedment_mm`, `plumb_deviation_mm`, `blow_count` each zero or more — `routes/arrays.py:132-137`
- §3.4 — insert — ambiguity — `driven_at` defaults to the current logical-clock instant when omitted — `routes/arrays.py:149`
- §3.4 — insert — ambiguity — remediation measurements zero or more; payload takes no `blow_count`/`driven_at` — `routes/arrays.py:164-168,179-184`
- §3.4 — insert — ambiguity — `modules_installed_qty` and `max_torque_tube_deviation_mm` both zero or more — `routes/arrays.py:193`
- §3.5 — insert — ambiguity — `insulation_resistance_mohm` and `measured_voc_v` zero or more; `ambient_c` unbounded and may be negative — `routes/arrays.py:274-279`
- §3.5 — revise — **mismatch** — the block is re-versioned only when a derived value actually moves, so a repeat passing retest of an already-`TESTED` circuit leaves the block's counters and `version` untouched — `calc.py:204-254`, `routes/arrays.py:299-300`
- §3.6 — insert — ambiguity — a refused advance writes nothing (previous `utility_witness_ref` survives a failed energization); no advance touches the project's `version` — `routes/grid.py:80-106`
- §4 — insert — ambiguity — pinned the filter sets for `GET /solar/deliveries` and `GET /solar/blocks`, previously described only as "Filtered" — `routes/yard.py:117-120`, `routes/arrays.py:70-74`

Judged already-pinned: pallet-ledger conservation and half-open pairwise-overlap capacity, `LIVE_DELIVERY_STATES`, `damage_ratio` 4 dp with the fork read off the rounded field at 0.05 inclusive, delivery state gates, body-FK resolution order and the ladder positions of the window/cross-project/OCC/capacity errors, the pile disposition truth table (0.90 refusal floor strictly-below, 12.0 mm plumb inclusive), `OUT_OF_TOLERANCE` producing no cascade, HOLD landings, remediation relief, module-availability summation, 25.0 mm tolerance inclusive, `mc_ready` conjunction, expected-Voc formula and the 3% band off the stored rounded expectation, INSULATION→VOC→POLARITY ordering, unbounded retest, "no blocks is never READY", the substation ladder, closed-interval backfeed coverage and window consumption, the ±120-minute closed buffer excluding DENIED, and outage-response gates. Backfeed-window tie-breaking deliberately not pinned: the conflict rule makes two overlapping `APPROVED` windows unreachable, so the ordering is unobservable.

### Pass C — §3.7 commissioning, §3.8 payroll, punch half of §3.9, plus a whole-`calc.py` backstop

506 → 506 lines, +3,019 chars. 13 ambiguity-pins, 3 mismatch-revisions.

- §3.7 — insert — ambiguity — `scheduled_at` is recorded as supplied and never compared to the clock, so a past instant schedules fine — `routes/commissioning.py:27,54`
- §3.7 — insert — ambiguity — `ambient_c` unbounded; a sample outside the weather envelope is appended with `is_valid` false rather than rejected — `routes/commissioning.py:91-102`, `calc.py:311-316`
- §3.7 — insert — ambiguity — appending an interval leaves the project's `version` untouched — `routes/commissioning.py:122-127`
- §3.7 — insert — ambiguity — finalization's optional `note` is persisted nowhere; finalization bumps only the test — `routes/commissioning.py:143,161-163`
- §3.8 — revise — **mismatch** — PRD called `week_start_date` "the Monday of the week"; impl validates no weekday, so any date opens a seven-day week from it — `routes/payroll.py:24-28,79`
- §3.8 — revise — **mismatch** — PRD read as constraining `hours` to two decimals; impl only enforces > 0 and echoes any scale, rounding only the ledgers — `routes/payroll.py:71`
- §3.8 — insert — ambiguity — the `work_date` span is `week_start_date`..+6 inclusive, checked after the week resolves but before its status, so a bad date in a certified week reports `ERR_INVALID_REQUEST` not `ERR_PAYROLL_WEEK_LOCKED` — `routes/payroll.py:77-82`
- §3.8 — insert — ambiguity — on void the line's own status is checked first, so an already-voided line in a certified week reports `ERR_LABOR_ENTRY_ALREADY_VOIDED` — `routes/payroll.py:141-145`
- §3.8 — insert — ambiguity — certification's optional `note` is persisted nowhere — `routes/payroll.py:164`
- §3.8 — insert — ambiguity — certification moves no hour ledger and leaves the project's `version` untouched — `routes/payroll.py:177-181`
- §3.8 — insert — ambiguity — a labor-compliance run re-derives figures only to total them; it rewrites, re-stamps and re-versions no labor entry and no payroll week — `routes/projects.py:163-171`, `calc.py:464-470`
- §3.8 — insert — ambiguity — a posted line is persisted with `void_reason` null — `routes/payroll.py:107`
- §3.8 — revise — **mismatch** — the conserved-hour-ledger identity qualified: the three week figures are each rounded independently from the raw lines — `calc.py:394-396`
- §3.9 — insert — ambiguity — a closure decision's optional `note` is persisted nowhere — `routes/punch.py:91`
- §3.9 — insert — ambiguity — a `REJECT` keeps `closure_evidence_ref`, `submitted_by_user_id` and `decided_by_user_id`; a fresh submission overwrites evidence + submitter, so SoD is measured against the most recent submitter — `routes/punch.py:103-107`
- §3.5 — insert — ambiguity (backstop) — a `REWORK` block clearing its failures with `circuits_tested_count` short of plan lands on `WIRED` when the wired count reached plan, else `PLANNED` — `calc.py:236-248`

**Backstop report:** every function and constant in `calc.py` was walked, not just those pass C's routes call. One behavior was undescribed anywhere — the electrical dimension's exit from `REWORK` when the tested count is still short of `planned_string_count` (`calc.py:236-243`); §3.5 had pinned only `REWORK → TESTED`. Pass C pinned both remaining landings inline as the final pass. `calc.ld_cap()` is dead code (settlement recomputes the cap inline) and needs no prose; the frozen `ld_cap_cents` behavior it duplicates is already pinned in §3.1/§3.9. Everything else traced to a pinning passage.

**Orchestrator final verification:**
- `PRD_COMPLETED.md` is 506 lines / 116,765 chars and is NOT byte-identical to `PRD_FINALIZED.md` — `diff` reports 88 changed lines. The scan genuinely ran.
- The document still terminates at the completed §5 error table (last row `ERR_CHANGE_ORDER_CAP_EXCEEDED | 422`); no truncation.
- Both earlier-pass marker phrases survive in the final file, confirming the three passes composed rather than overwrote one another.
- Every file under `workspace/implementation/` has an mtime at or before 17:01, while `results.1.json` is 17:53 — no implementation byte changed after the green sweep, so the 8/8 × 207/207 result still describes the delivered code.

**PIPELINE COMPLETE.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
