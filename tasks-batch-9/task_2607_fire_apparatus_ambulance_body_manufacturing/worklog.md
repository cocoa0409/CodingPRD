# Worklog — task_2607_fire_apparatus_ambulance_body_manufacturing

## Step 1: Create task directory — 2026-09-03T18:43:37.956Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2607_fire_apparatus_ambulance_body_manufacturing` and `.../workspace`. Index 2607 was pre-assigned by the invoking pipeline; no auto-allocation scan was performed (32 concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-03T20:29:21.943Z

All three scaffold artifacts for task 2607 are complete and lint-clean.

## Output files (`/home/ubuntu/github/CodingPRD/tasks/task_2607_fire_apparatus_ambulance_body_manufacturing/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3030 | 148319 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2116 | 138263 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4726 | 296821 |

`SCAFFOLD.yaml` holds §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys, machine-verified); each design file has exactly one top-level key.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1111

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold surface
12 entities, 10 state machines (parallel build/certification dimensions), 2 OCC concurrency rules, 11 calculations, 53 prioritized validations, 61 endpoints, 63 errors, 5 roles; `complexity_profile` = compliance_audit / multi_party_negotiation, layers `cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency`, role_model `segregation_of_duties`, consistency `immediate`. Logical clock defaults to 2026-08-01T00:00:00Z with `POST /programs/{id}/ops-run` as the only sweep.

## §1.9 corner design
82 entries across all nine claim-extraction sections — 54 full instances + 28 `excluded_because` stubs (entities 12, state_machines 19, calculations 14, validations 17, endpoints 3, errors 7, rbac 3, complexity_layers 6, consistency_model 1). Verified programmatically: 100 instance names unique across both design files, zero unbound `${var}` references in any recipe, every stub cites a real §1.8 instance and carries no `test_recipe`, and every non-stub carries one. All 63 error ids are triggerable (each either asserted in a §1.9 instance or covered by a cited §1.8 instance).

Two fixes made this session:
- **Self-consistency defect in `SCAFFOLD.yaml`** (line ~1284): the `WarrantyStartup` state-machine note claimed a delivery with `training_hours >= 16.0` is born ACTIVE, contradicting `calculations.warranty_activation_window`. Rewritten so delivery *always* creates `PENDING_TRAINING` with the 30-day deferred start and `complete-training` is the only path to ACTIVE.
- **Lint (e) violation**: `existence_checks_reject_before_optimistic_concurrency` used literal `expected_*_version: "99"`. Added a real spec-release + unit-order chain to its setup so both OCC fields are genuine captured `${var}`s aimed at fabricated parent ids — which strengthens the claim (404 wins over 412 even with a live version).

Deliberate omission worth flagging for the PRD/test phase: the `InspectionTrip` MID_CONSTRUCTION-hold precondition (`unit.build_status == IN_PRODUCTION`) has **no declared error id** in §1.6, so no instance asserts it rather than inventing an error.

## Step 3: Copy shared files — 2026-09-03T20:29:21.943Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:46:00.000Z

Document complete. All three Hard Contracts pass.

## Output

`workspace/PRD.md`

- **Final line count: 546**
- **Exact last heading: `## 5. Data Validation & Error Handling`**
- Document ends at a real section boundary: the complete 63-row §5 error table, final row `| `ERR_ESCALATION_YEAR_OUT_OF_RANGE` | 422 |`. No audit footer, no truncation, no contract reports inside the file.
- Structure: §1 Introduction, §2 with 12 subsections (2.1–2.12), §3 with 9 subsections (3.1–3.9), §4 with **61** endpoint rows in a 4-column table, §5 with **63** error rows in a 2-column table. 21 `###` headings total.
- Built incrementally: 1 `Write` + 8 `cat >> … <<'PRDEOF'` heredoc appends, plus one small `Edit`. No single oversized write.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS (two independent passes).**
- Pass 1 against the pre-built 120-token set (all entity `fields[].name` ∪ endpoint `input`/path identifiers ∪ `line_items` sub-keys `description`/`quantity`/`unit_cost_cents`/`markup_pct`/`is_taxable` ∪ ops-run output keys `expired_reservation_count`/`warranty_activated_count`/`warranty_expired_count`/`program_status`): **0 missing**, all present inside backticks (code fences stripped before pairing so the §2.2 JSON block cannot create false positives).
- Pass 2 re-derived the set directly from `SCAFFOLD.yaml` (130 tokens): **0 missing** field/input/path/output identifiers. The only 15 derived names absent are calculation ids and variant labels (`unit_award_price`, `axle_load_distribution`, `award_year_locked`, `delivery_year_actual`, `strict`, `provisional`, etc.), which are scaffold internals SKILL.md forbids naming — their semantics are in prose instead.

**Contract 2 — Rule Coverage: PASS.**
- All **53** validation rungs transcribed as a numbered ladder in §2.9, each with its error id, HTTP status and applies-to scope; count verified equal to the 53 `priority:` entries in the scaffold.
- All **63** error ids appear in prose before §5 (the 21 cross-cutting auth/shape/existence/version/wrong-state ids live in §2.7 and §2.9 by design; the other 42 are additionally anchored in §3 workflow prose).
- All 10 state machines, every enum member, all 3 named cascades, both compensating invariants and both OCC rules are covered. Constant *values* appear in prose (3.5, 50,000,000, 1.25, 90,000,000, 1.00, 0.75, 6.5, 22.0, 3,400/28, 1,800/12, 900/20, 450, one quarter, 80, two seats, 90, weights 3 and 1, 75.00, 40.00, 16.0, thirty days) without ever naming the scaffold constant identifiers.
- Scanned clean for operator syntax (`>=`, `<=`, `!=`, `->`, `+=`, …), pseudocode calls, scaffold self-references (`calculations.`, `validations[`, `priority=`) and fuzzy words — zero hits.

**Contract 3 — §3 Path Purity: PASS.** Over 893 backticked tokens in §3: zero tokens containing `/`, zero tokens beginning with an HTTP method, zero bare `METHOD /path` strings, zero bare HTTP method words, zero path-like strings. §1 and §2 are equally clean; paths and methods appear only in §4.

## Two scaffold defects worked around
1. **Certification-submitter role conflict.** `endpoints[]` and `roles[].exclusive_operations` assign certification-test submission and result recording to `ThirdPartyTester`, but the `certification_status` state machine names `BodyEngineer` as actor and `CertificationTest.submitted_by_user_id`'s description says "the `X-User-ID` of the BodyEngineer". Resolved in favour of the RBAC matrix (validation priority 2 keys off `endpoints[].roles`); `submitted_by_user_id` is described role-neutrally so both readings stay consistent.
2. **Mis-referenced validation priority.** The soft-ceiling auto-suspend transition cites `validations[priority=27]` for a strict-ceiling breach; the real rung is priority 52, `ERR_CONTRACT_CEILING_EXCEEDED`. The PRD names the correct error id.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator anti-truncation check (independent):** `wc -l` = 546; `grep -n '^#'` shows 26 headings ending at `## 5. Data Validation & Error Handling` (line 478); `tail -15` shows a complete markdown table row. Confirmed NOT truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T22:22:12.778Z

Stage 2 is complete. The full suite now covers every non-stub instance in both design indices.

## Output (both directories at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 9 files, 2097 lines
`__init__.py` 112, `api_client.py` 293, `api_errors.py` 155, `assertions.py` 207, `constants.py` 131, `factories.py` 223, `fixtures.py` 525, `test_users.py` 78, `types.py` 373

`test_suite/` — `conftest.py` (53) + 19 test modules, 6460 lines total, **90 tests**
test_01 291/6, test_02 340/6, test_03 309/5, test_04 470/7, test_05 489/7, test_06 508/7, test_07 544/6, test_08 324/3, test_09 449/5, test_10 176/2, test_11 251/4, test_12 215/4, test_13 267/4, test_14 278/4, test_15 319/4, test_16 308/4, test_17 280/4, test_18 288/4, test_19 301/4 (lines/tests)

New this segment: `test_18_resource_temporal_overlap.py`, `test_19_compensating_invariants.py`, plus one appended test in `test_04` (`build_status_rejects_out_of_order_and_post_cancel_transitions`, the one non-stub corner instance that had been missed).

## Coverage verification (scripted over both yamls)
- 90 tests, 90 `Design:` tags — every test has exactly one, always the last docstring line; zero untagged, zero dual-tagged, zero tags pointing at a non-existent instance.
- Queue A: all 18 difficulty instances, **2 tests each** (36).
- Queue B: **54 / 54 non-stub corner instances**, >=1 test each (54). None of the 28 `excluded_because:` stubs was translated.
- 218 PRD citations checked programmatically against `workspace/PRD.md`: every quoted fragment now matches verbatim (whitespace-normalised, `...` elision honoured) **and** sits in the section number cited.
- Gates: `py_compile` clean on all 29 files; `pyflakes test_suite/*.py` rc=0 with empty output; `pyflakes test_helpers/*.py` clean except the intentional re-export noise in `__init__.py`; `import test_helpers` succeeds; every `from test_helpers import ...` name and every `api.<method>` call resolves. Both `__pycache__/` dirs removed.

## Citation defects found and fixed in earlier files during the final pass
- `test_05`: two quotes cited PRD 2.2 (actually 2.6), two cited PRD 3.1 (actually 2.10).
- `test_09`: three paraphrased quotes replaced with verbatim text — the change-order submit gate (real text is the PRD 3.8 negotiation-cycle sentence), the award's `ERR_SPEC_NOT_RELEASED` gate (PRD 3.5 "The pinned specification must be `RELEASED`..."), and a hand-written "PRD 2 (consistency model)" gloss plus two invented one-line restatements of `committed_cents` and `available_slot_count` (now PRD 2.8 / 2.10 / 3.6 verbatim).
- `test_08`: PRD 4 endpoint-table quote said "Moving the logical plant clock"; the table says "Sets the logical plant clock".
- `test_10`: dropped the `**` emphasis from "The **soft ceiling** is ninety percent...".
- Also removed two dead imports in `test_helpers/fixtures.py`.

## Design-index divergences (skipped or corrected; gaps left as gaps)
- @136 sequenced a disposition after submit-review, which the PRD refuses (rung 11 needs the parent spec `DRAFT`); helper leaves the spec `DRAFT`.
- @3390 asserts `months_elapsed` 31; the PRD's whole-month rule gives 32 -> 69,858,334 / variance 1,582,334.
- @3867 setup releases a specification whose strict score is 60.00, below the 75.00 release gate.
- Several recipes use `long_lead_status` values `SLOT_CONFIRMED` / `SLOT_RESERVED`; the PRD enum is `CONFIRMED` / `RESERVED`.
- One stale-version instance reuses an award-time unit version after a version-bumping hold.
- A bond-tier mislabel in an inline rationale; `failure_note` / `rejection_note` payload fields that do not exist in the PRD; `expiry_at` echo format not pinned by the PRD.
- PRD §2.9 rung 4 omits `ERR_CLAUSE_NOT_FOUND` / `ERR_PLANT_BAY_NOT_FOUND` although rung 5 and §5 include them.
- @1234 claims the `front_over` unit proves the ordering "and NOT OVER_REAR", but with rear rating 10,110 against rear load 10,110 the rear leg is not violated at all — that unit demonstrates only the front boundary, so the test asserts only what the PRD derives.

No server was started, no `pkill` was ever run, `workspace/implementation/` was never read, and no sibling task directory was touched.

## Step 6: Generate implementation — 2026-09-03T22:22:12.778Z

Implementation is complete and verified.

## What exists

`workspace/implementation/`

```
app.py            56    routes/__init__.py     1
calc.py          422    routes/certs.py      180
db.py             92    routes/changes.py    244
errors.py         97    routes/programs.py   152
find.py           61    routes/specs.py      303
middleware.py     73    routes/supply.py     352
response.py       72    routes/units.py      264
services.py      361
timeutil.py       78    requirements.txt       1
validate.py      240    start.sh              10   (mode 755)
                                       total 3059
```

Byte sizes from `ls -la`: app.py 1624, calc.py 14511, db.py 2581, errors.py 3778, find.py 1652, middleware.py 1957, response.py 2004, services.py 12608, timeutil.py 2625, validate.py 7589, start.sh 399, requirements.txt 13; routes/ — certs 6007, changes 8569, programs 5099, specs 10741, supply 12215, units 10006, `__init__` 74. No `__pycache__`, no data files, nothing on disk but source.

## Boot check (mandated)

`PORT=18607 bash start.sh` -> Flask bound 0.0.0.0:18607, PID **1602191** confirmed as the port owner via `ss -ltnp`. `GET /programs` without headers -> `401 ERR_MISSING_AUTH_HEADERS`; with `X-User-ID`/`X-User-Role: ProgramAdmin` -> `200` with the empty-list envelope (`total_count: 0`, proving no seeding). Killed with `kill -TERM 1602191` only — PID gone, port free. No pattern kill was ever issued; the host had 20+ other `python3 app.py` pipelines running and all were left untouched.

## Functional verification

143 assertions across two scratch scripts in `/tmp/t2607smoke/` (Flask test client, outside the implementation dir), **zero failures**.

Every worked numeric reference in the PRD reproduces exactly: award price 68,276,000 / 70,665,660 with option premium; tier-boundary bond at subtotal exactly 50,000,000 -> 50,625,000; axle 5810/10110/15920 `WITHIN_LIMITS` and `OVER_REAR` at +1 kg rear; change-order delta 2,446,181 under per-line rounding; compliance 50.00 strict / 87.50 provisional; delivery-year final 70,279,166 with variance 2,003,166; buffered slot conflict on back-to-back windows plus admission at +7 days; bay aggregate capacity admitting exactly 12; deferred warranty 2026-12-01 -> 2031-12-01 pulled back to 2026-11-01 -> 2031-11-01 at exactly 16.0 hours.

Also confirmed green: soft ceiling at exactly 90% is not a breach while 1 cent over auto-suspends with `SOFT_CEILING_BREACH`; `ERR_CONTRACT_CEILING_EXCEEDED` persists nothing (committed_cents unchanged); `ERR_SOFT_CEILING_STILL_BREACHED` clears only after a decommit; Cascade A/B/C all hop correctly, including Cascade B leaving `build_status` alone while tearing up the certificate as `SPEC_SUPERSEDED`, and rescission restoring money and axle loads without restoring certification; committee scope rejecting a foreign program's rep; ladder ordering where the restrictive-ratio gate (rung 45) fires ahead of the compliance-score gate (rung 46).

## Fixes made in this pass

- `validate.body()` now parses with `get_json(silent=True, force=True)` so a JSON payload sent without an `application/json` content type is accepted rather than becoming a spurious `ERR_INVALID_REQUEST`.
- Removed an unused `import services` from `routes/certs.py`; `pyflakes` on the whole tree is now clean.

Constraints honored: in-memory dicts only, no seeding, `test_suite/`, `test_helpers/`, the two SCAFFOLD design files, and all sibling task directories were never read or listed; all writes were chunked (`Write` + `cat >>` heredocs), so nothing was lost to the output cap.

**Orchestrator layout check:** `test_helpers/` (9 files) and `test_suite/` (20 files) both confirmed at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist. No relocation needed.

## Step 7: Run tests and iterate — 2026-09-03T22:45:00.000Z

Clean sweep confirmed. All 8 rounds: `passed == total` = 90/90, fresh mtimes (22:42:30), ~173s each.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps.
- Sweep 1: 72/90 in all 8 rounds, byte-identical failure sets -> deterministic, 18 distinct failures in 6 root-cause groups.
- Sweep 2: 89/90 in all 8 rounds (one regression I introduced myself).
- Sweep 3: **90/90 in all 8 rounds.** Artifacts: `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. Every failure resolved to a test/test_helpers defect, and each was fixable under STEP 1c (split: keep the covered assertion, drop the uncovered one) or STEP 2 (fixture inconsistent with PRD). No PRD-silence deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — replaced `assert_created_at_default_clock` with `assert_created_at_precision`: PRD §2.5 pins only that `created_at` is "an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written"; §2.4 scopes the logical clock to "every deadline, expiry, window comparison and warranty date", so pinning `created_at` to the clock instant was not uniquely derivable. Kept the verbatim precision assertion.
- `test_helpers/assertions.py` — added `assert_clock_stamp(actual, expected_instant)`: PRD pins *which* instant `held_at`/`confirmed_at`/`applied_at`/`delivered_at` carry ("stamps `held_at` with the current logical clock") but never their fractional-digit rendering, so the exact instant is still asserted, compared as an instant rather than a string.
- `test_helpers/assertions.py` — added `assert_updated_at_refreshed(record)` plus the `_instant` parser: PRD §2.5 says `updated_at` is "refreshed on every mutation", which pins ordering relative to `created_at`, not equality.
- `test_helpers/fixtures.py` — `setup_unit_at_stage`: merged `pre_trip_overrides` / `mid_trip_overrides` into field dicts before splatting into `schedule_trip`. Previously the literal `scheduled_start`/`scheduled_end` plus the same key in the overrides raised `TypeError: got multiple values for keyword argument`, aborting 3 tests in setup.
- `test_helpers/constants.py` — dropped the now-unused `DEFAULT_CLOCK_STAMP`.
- `test_helpers/__init__.py` — export list updated for the added/renamed helpers.

**Fixes applied to `test_suite/` (STEP 2, fixture violated a PRD precondition):**
- `test_05_pricing_and_score_calculations.py` — `test_a_full_slot_line_refuses_a_non_overlapping_window_on_the_count` sent `slot_start_date=2027-01-01` with `expiry_at=2026-12-01`, which trips ladder rung 35 ("`expiry_at` is strictly later than `slot_start_date` — otherwise `ERR_INVALID_SLOT_WINDOW`, 422") *above* the exhaustion rung. Both payloads' `expiry_at` moved to `2027-04-01`; the implementation's precedence was correct.
- `test_16_boundary_precision.py` — two clauses used `"category": "BODY"`, not a member of the PRD §3.2 enum (`CHASSIS`, `PUMP`, `AERIAL`, `PATIENT_COMPARTMENT`, `ELECTRICAL`, `PAINT`); the 400 was correct. Changed to `PATIENT_COMPARTMENT`.
- `test_09_clock_sweep_and_listings.py` — the sweep test expected a hold to be `CONFIRMED`, but its own setup carried that unit into production; PRD §3.6: "when the unit the reservation is tied to starts production, the reservation moves from `CONFIRMED` to the terminal `CONSUMED` state" and "A `CONSUMED` reservation still occupies its slot". Assertion corrected to `CONSUMED` with those quotes added to the docstring.
- Assertion-helper call sites retargeted in `test_01`, `test_04`, `test_08`, `test_09`, `test_10`, `test_11`, `test_14`.

**Fixes applied to `implementation/`: none.** The implementation was PRD-faithful in all six root-cause groups — ladder rung ordering, the CONSUMED transition, clause-enum validation, and both timestamp renderings were all correct as written. No endpoint, field, side effect, or seed data was added, and no PRD-required check was weakened.

**Orchestrator independent verification:** all 8 `results.$i.json` present with mtime 22:42, each parsed as `passed=90 total=90 failed=0`. Clean sweep confirmed from artifacts, not from the subagent's claim alone.

**Step 8 skip-condition adjudication (orchestrator decision, no user available):** Step 7 reports 0 deletions and 0 `implementation/` fixes, but NOT zero iterations — 3 sweeps ran, with substantive `test_helpers/` and `test_suite/` fixes. The skill's skip condition requires all four counters at zero (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes). Two of the four are non-zero, so Step 8 RUNS. The test-side fixes are themselves PRD-silence evidence — three of them (the `created_at` clock-vs-write-time ambiguity, the `held_at`/`confirmed_at`/`applied_at`/`delivered_at` fractional-digit rendering, the `updated_at` refresh semantics) are exactly the "impl pinned a choice PRD left open" pattern Step 8 exists to close.

## Step 8: Finalize PRD — 2026-09-03T22:49:03.442Z

Done. `PRD_FINALIZED.md` written with three surgical edits.

## Line counts
- `PRD.md`: 546 lines
- `PRD_FINALIZED.md`: 546 lines (0% line delta; 3 lines revised in place, no new sections)

## Changes
- **§2.4 (Logical Plant Clock)** — *revise* — pinned that the clock is held as the exact text it was last set with, that the echo returns it verbatim, and that every clock-stamped business field (`released_at`, `confirmed_at`, `held_at`, `applied_at`, `delivered_at`) stores that text unchanged rather than re-rendering to three fractional digits (so at startup default they read exactly `2026-08-01T00:00:00Z`), while comparisons use the denoted instant — `implementation/services.py:15-17` + `db.py:16,46-47`, callsites `routes/specs.py:151`, `routes/supply.py:177,329`, `routes/changes.py:205`, `routes/units.py:211`.
- **§2.5 (Record Identity, Audit Fields)** — *insert* — pinned that `created_at` and `updated_at` come from the server's real UTC wall clock, never from the logical plant clock — `implementation/db.py:59,86` via `timeutil.py:16-19`.
- **§2.5 (Record Identity, Audit Fields)** — *revise* — pinned that `updated_at` equals `created_at` on a freshly created row and is refreshed on each mutation to that mutation's wall-clock instant, so it never precedes `created_at` — `implementation/db.py:62,86`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 clock-stamp rendering**
- (a) Subject: the textual rendering of any field stamped from the logical clock, and the clock's own storage/echo.
- (b) Enumerated & read: `services.py:15-17` (`clock_raw()` returns `db.clock_raw`, the raw string); every callsite found by grepping `clock_raw|held_at|confirmed_at|applied_at|delivered_at|released_at` — `routes/specs.py:151`, `routes/supply.py:177`, `routes/supply.py:329`, `routes/changes.py:205`, `routes/units.py:211` (all five identical, no normalisation); `db.py:16` (`CLOCK_DEFAULT_RAW`), `db.py:42-47` (`clock` property parses, `set_clock` stores raw); `validate.py:154-159` (`req_dt` returns raw client text); `routes/programs.py:25-31` (echo of `db.clock_raw`); consumers that compare rather than render — `services.ops_run` (`parse_dt` on `expiry_at`, `warranty_start_date`, `warranty_end_date`) and `calc.py`; adjacent-but-different paths deliberately excluded — `certs.py:40,69` (`tested_at` is client-supplied verbatim, not clock-stamped) and `calc.py:421-422` / `timeutil.format_like` (warranty dates rendered from the `delivery_date` template, not the clock).
- (c) Adjustment: named `released_at` alongside the four Step 7 fields, since `specs.py:151` uses the identical mechanism and a four-field list would have implied release differs. Added the closing clause "Comparisons against the clock... are made on the instant that text denotes" so the sentence cannot be read as making the clock a pure string and breaking `ops_run`'s instant comparisons. Scoped the claim to "field that records a clock instant" so `tested_at` and the warranty window dates are not swept in.

**Edit 2 — §2.5 audit-stamp time source**
- (a) Subject: which clock writes `created_at` / `updated_at`.
- (b) Enumerated & read: `db.py:57-65` (`new_row`, the sole mint path) and `db.py:68-87` (`touch`, the sole refresh path); `timeutil.py:16-19` (`now_iso`, real wall clock, three fractional digits); full-tree grep for `created_at|updated_at` writers confirmed no other writer exists; all `new_row` callers checked for overrides (`programs.py:55`, `specs.py:55-70` + clause, `supply.py:45,117,209,258`, `units.py:72`, `changes.py`, `certs.py`, `services.py:270`) — none override; immutable rows `plant_bay` (`supply.py:209-212`) and clause use `versioned=False`, so they carry `created_at` and no `updated_at`; `response.py:25` (`meta.api_request_timestamp`) also uses `now_iso`.
- (c) Adjustment: wrote "`updated_at` **wherever a resource carries one**" so the sentence does not contradict §2.5's own immutable-resource paragraph (clause and plant bay have no `updated_at`). Softened an initial draft that said the audit stamps are "the one place the server reads real time" to "unlike the business fields, the audit stamps do read real time", because `meta.api_request_timestamp` also reads real time and the absolute claim would have mis-described `response.py:25`.

**Edit 3 — §2.5 `updated_at` refresh semantics**
- (a) Subject: `updated_at`'s value at creation and after each mutation.
- (b) Enumerated & read: `db.py:62` (`row["updated_at"] = row["created_at"]` at mint), `db.py:86` (`row["updated_at"] = now_iso()` on touch), `db.py:75-84` (touch is a no-op for unversioned rows and dedups per request, so a multi-hop cascade refreshes a row once); every cascade path that re-touches the same row — `services.apply_change_order_cascade` (hops 1/2/3 all touch the unit), `services.invalidate_certification`, `services.release_reservation`, `services.supersede_predecessor`, `services.ledger_sync`, `services.sync_slot_line`.
- (c) Adjustment: phrased the post-mutation value as "the wall-clock instant of that mutation, so it never precedes `created_at`" rather than "strictly later than `created_at`" — the per-request dedup plus millisecond resolution means a cascade-touched row can legitimately carry an `updated_at` equal to its `created_at`, and a strict-ordering claim would have been a false universal. Left §2.5's existing "increments by one on every mutation of that row" and §2.8's "increments by one" untouched, since those already read as one increment per row per request, which is what `touch`'s dedup implements.

**No PRD edit for** the `test_helpers/fixtures.py` `TypeError`, the `test_05` slot-window payload, the `test_16` clause category, or the `test_09` `CONSUMED` expectation: rung 35 sits above rung 39 in the existing ladder (matching `routes/supply.py:108-115`), §3.2 already enumerates the six clause categories, and §3.6/§3.9 already pin the `CONFIRMED`->`CONSUMED` transition at production start and that a `CONSUMED` reservation still occupies its slot (matching `routes/units.py:157-163`). All four were pure test-side defects.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` returns 12 lines covering exactly 3 changed lines (94, 98, 100) — a real, minimal, non-empty diff. Both files 546 lines.

## Step 9: Complete PRD — 2026-09-03T23:15:36.172Z

**Orchestrator decision:** run Step 9 as three sequential file-partitioned passes over `implementation/` rather than one monolithic scan. Rationale: a single-pass scan of a 3059-line implementation against a 546-line PRD has historically produced a byte-identical no-op output. Partitioning bounds each subagent's reading load and makes the "did the scan actually run" check falsifiable (34 diff hunks vs PRD_FINALIZED.md, +10,107 chars). Partitions: (1) app/db/errors/find/middleware/response/timeutil/validate/calc, (2) routes/programs+specs+supply, (3) routes/units+changes+certs and services. Passes 2 and 3 were told explicitly not to re-copy PRD_COMPLETED.md, only to Edit in place.

### Pass 1 — infra + calculations (11 edits: 8 ambiguity-pins, 3 mismatch-revisions)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` done; 546 lines, every edit an in-paragraph insert/revision.

- **§2.1 (L17)** — revise — ambiguity — an empty-valued `X-User-ID`/`X-User-Role` counts as absent (401), and the role must match one of the five names exactly — `middleware.py:33`
- **§2.2 (L53)** — insert — ambiguity — `meta.api_request_timestamp` comes from the real UTC wall clock, not the logical plant clock — `response.py:25`, `timeutil.py:16`
- **§2.3 (L88)** — insert — ambiguity — filters are exact string comparisons; an empty filter value is treated as absent; filter values are validated against neither an enum nor an existing row, so an unknown value yields an empty page rather than 400/404 — `validate.py:199`
- **§2.5 (L100)** — revise — ambiguity — `version` is **1** on a fresh row, and increments **once per request**: several rules/cascade hops touching one row still yield +1 and one `updated_at` refresh — `db.py:57`, `db.py:68`
- **§2.6 (L112)** — revise — **mismatch** — PRD claimed `escalation_index_pct_per_year` is "carried to one decimal place" and training hours "compared at one fractional digit"; impl neither quantises nor limits precision (4.55 stored/echoed verbatim) and compares the accumulated training figure exactly. Also pinned that two-decimal scores are emitted as JSON numbers (so `40.00` renders `40.0`) — `validate.py:107`, `response.py:34`
- **§2.6 (L114)** — revise — **mismatch** — PRD claimed interval comparisons are "at second resolution"; impl compares the denoted instants at full supplied precision. Also pinned accepted ISO 8601 input forms and verbatim storage/echo — `timeutil.py:28`, `validate.py:154`
- **§2.9 rung 3 (L148)** — revise — ambiguity — JSON parsed regardless of `Content-Type`; absent/empty body = empty object; non-object body rejected; explicit `null` == omitted; no string coercion, booleans rejected for numerics, integer fields reject any decimal-point number (`3.0` included) while decimal fields accept bare integers, string lengths measured untrimmed; empty `limit`/`offset` = omitted, non-base-ten text rejected — `validate.py:22,37,82,107,171`
- **§2.12 (L222)** — insert — ambiguity — rows tied on millisecond-resolution `created_at` are ordered by server write sequence — `db.py:90`
- **§3.8 (L354)** — revise — ambiguity — line-item entries are JSON objects with extra keys ignored, `description` non-empty with no max length, `is_taxable` required with no default, and only the **lower** bound on `markup_pct` is a rung-3 rule — `validate.py:206`
- **§3.9 (L400)** — insert — ambiguity — derived warranty dates rendered in the supplied `delivery_date`'s own textual style; an undeferred start is the `delivery_date` text byte-for-byte — `timeutil.py:46`, `calc.py:416`
- **§5 intro (L480)** — insert — **mismatch** — the status table governs declared endpoints only; unknown path / undeclared method returns `ERR_INVALID_REQUEST` under 404/405 rather than 400; a trailing slash addresses the same endpoint — `app.py:35,21`

Verified live (PID 2634685, port 18747, killed by exact PID). Judged already uniquely pinned: the full 60-id `ERROR_HTTP_STATUS` map, `find.py` 404 ids, auth rungs 1/2 and committee-scope rung 6, envelope shapes, pagination defaults/bounds, and every `calc.py` constant and formula (award 7-step price, bond tiers, pro-rata months, per-line markup+tax, payload models, axle model, clause weights, restrictive ratio, 30-day deferral, 16.0-hour threshold, month-add clamping).

### Pass 2 — programs/specs/supply routes (13 edits: 9 ambiguity-pins, 4 mismatch-revisions)

546 lines on entry, 546 on exit; file not re-copied; pass 1's edits verified intact.

- §2.7 — insert — ambiguity — `expected_slot_line_version` is an integer >= 0, so absent/negative/non-integer is a rung-3 `ERR_INVALID_REQUEST`, not a 412 — supply.py:92-94
- §2.9 rung 3 — revise — mismatch — body parsing/JSON-object rejection runs only where the operation declares at least one body field; a fieldless transition endpoint never inspects the body (exactly 17 of 37 POSTs call `validate.body()`) — programs.py:94/106/118/134/149, specs.py:98/113/126, supply.py:170/191/303/346
- §2.9 rung 12 — insert — ambiguity — the trip-hold milestone check reports the same `ERR_INVALID_BUILD_STATE` but sits below rungs 18 and 41 — supply.py:323-326
- §2.10 — insert — ambiguity — a `contract_ceiling_cents` below `base_unit_price_cents` is rejected at rung 3 with `ERR_INVALID_REQUEST` / 400 — programs.py:50-53
- §3.2 — insert — ambiguity — `program_id` resolved before `supersedes_spec_id`; drafting checks nothing else about the predecessor — specs.py:45-49
- §3.2 — revise — mismatch — "four derived figures" -> "five" (clause_count, mandatory_clause_count, both scores, ratio) — specs.py:195 -> services.py:48-52
- §3.3 — insert — ambiguity — `specification_id` resolved before `clause_id`; `exception_text` >= 1 char, no upper bound — specs.py:228-234
- §3.3 — insert — ambiguity — `disposition_note` >= 1 char, no upper bound — specs.py:291
- §3.6 — insert — ambiguity — references resolved `program_id` -> `unit_order_id` -> `slot_line_id`, first miss reported — supply.py:96-98
- §3.6 — revise — mismatch — `long_lead_status` becomes `RESERVED` from whatever it held (`NOT_RESERVED` or `AT_RISK`), the unit's `version` increments, and no build-state guard governs the earmark — supply.py:133-136
- §3.7 — insert — ambiguity — `unit_order_id` resolved before `plant_bay_id` — supply.py:246-247
- §3.7 — revise — mismatch — dropped "evaluated at second resolution"; the intersection test runs on the instants the texts denote at their own precision — calc.py:300-322 via supply.py:254
- §3.7 — insert — ambiguity — milestone mismatch is `ERR_INVALID_BUILD_STATE`/409 evaluated last; `PRE_CONSTRUCTION` carries no build-state requirement — supply.py:319-326

Two cross-partition items were handed to pass 3 rather than guessed at.

### Pass 3 — units/changes/certs routes + services (14 edits, 12 lines: 12 ambiguity-pins, 2 mismatch-revisions)

546 lines on entry, 546 on exit; all 34 hunks vs PRD_FINALIZED.md are pure line substitutions (`NcN`); passes 1-2 edits spot-verified intact.

- §2.7 — revise — mismatch — **handoff (a)**: replaced "evaluated before any state, referential, capacity or fiscal rule" with wording that puts both OCC checks *below* the rung-4/5 404s and committee scope and *above* own-state/cross-entity/referential/temporal/capacity/fiscal rules — changes.py:58-66, supply.py:96-102
- §2.9 rung 3 — insert — ambiguity — **handoff (b)**: unrecognised body keys are ignored, top level as much as inside a line item, never stored or echoed — validate.py:22-34
- §2.7 — insert — ambiguity — `expected_unit_order_version` is an integer >= 0, so absent/negative/non-integer is a rung-3 400, not a 412 — changes.py:54
- §3.5 — insert — ambiguity — `program_id` resolved before `specification_id` on award — units.py:44-45
- §3.5 — insert — ambiguity — `award_year`'s rung-3 bound is only a 0-9999 sanity range; the program-relative window is rung 53 — units.py:34
- §3.5 — insert — ambiguity — `weight_calc_engineer_user_id` is a non-empty string with no upper length bound — units.py:42
- §3.8 — insert — ambiguity — `unit_order_id` resolved before `inspection_trip_id` on raise — changes.py:58-59
- §3.8 — insert — ambiguity — submit/negotiate/revise do not touch the unit order at all — changes.py:121-175
- §3.8 — insert — ambiguity — rescission never *drives* the certification teardown: a rescission whose recomputed verdict leaves `WITHIN_LIMITS` writes the new `weight_status` and stops — services.py:245-257
- §3.9 — revise — mismatch — `tested_at` is recorded at *submission*; record-result declares no `tested_at` field, so it stays whatever submission supplied, null included — certs.py:101-128 vs certs.py:40,69
- §3.9 — insert — ambiguity — `signed_by_user_id` is a non-empty string with no upper length bound — certs.py:106
- §3.9 — insert — ambiguity — `final_price_cents` and `price_variance_cents` live on the warranty startup row, not on the unit order — services.py:265-284
- §3.9 — insert — ambiguity — `additional_training_hours` is >= 0.0 with no upper bound (unlike handover's 0.0-200.0 `training_hours`) — certs.py:160
- §3.9 — insert — ambiguity — unit cancellation is written `CANCELLED` *before* the hold is released, so Cascade C's at-risk hop cannot fire: `long_lead_status` left as-is, no `PRE_CONSTRUCTION` trip cancelled, `chassis_reservation_id` ends null in every case — units.py:232-264, services.py:172-179
- §3.1 — insert — ambiguity — the sweep leaves the warranty record `ACTIVE` when it activates a unit, and `warranty_activated_count` counts only unit orders that actually moved out of `DELIVERED` — services.py:324-334

One unreachable silence deliberately left unpinned rather than invented into the PRD: `deliver` skips rung 37 when the unit has no `HELD` `MID_CONSTRUCTION` trip (units.py:203-206), a state a `FINAL_INSPECTED` unit cannot occupy.

### Step 9 totals and orchestrator verification

- **38 edits total** (32 ambiguity-pins, 9 mismatch-revisions across the three passes; two edits absorbed both categories).
- Line counts: PRD.md 546 / PRD_FINALIZED.md 546 / PRD_COMPLETED.md 546. Char counts: 113,588 / 114,646 / 124,753 — PRD_COMPLETED.md is **+10,107 chars over PRD_FINALIZED.md**.
- md5 of all three files distinct (`00cba470…` / `cc562dae…` / `a6a6d1bf…`); `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 34 hunks, `diff PRD.md PRD_COMPLETED.md` = 36 hunks. The scan genuinely ran — PRD_COMPLETED.md is NOT a copy of either predecessor.
- Post-hoc integrity check: no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` has an mtime later than the green sweep's `results.1.json` (22:42). Latest impl mtime is 21:11. The certified 8-round 90/90 sweep therefore still describes the artifacts on disk.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written.
