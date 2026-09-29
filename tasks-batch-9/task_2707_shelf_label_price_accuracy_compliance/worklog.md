# Worklog — task_2707_shelf_label_price_accuracy_compliance

## Step 1: Create task directory — 2026-09-04T09:40:45.458Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance` and `.../workspace` (pre-assigned path from the orchestration prompt; no index auto-allocation performed, per instruction that other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T11:41:37.733Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines | Bytes |
|---|---|---|
`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/SCAFFOLD.yaml` | 3178 | 162 KB |
`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2272 | 167 KB |
`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/SCAFFOLD_CORNER_DESIGN.yaml` | 5179 | 371 KB |

Top-level keys verified: `SCAFFOLD.yaml` carries neither design key; each design file has exactly one (`scaffold_difficulty_design`, `scaffold_corner_design`).

## Scaffold shape (§1.0–§1.7)

`api_prefix: /price-integrity`, difficulty `expert_plus`, topology flat, state-machine shape parallel, role model segregation_of_duties, consistency immediate, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation]`.

15 entities · 68 endpoints · 66 error codes · 12 calculations (2 dual-variant, 3 combinatorial modes) · 11 state machines (2 cyclic loops, 1 two-axis parallel, 2 branching) · 3 OCC rules · 35 priority-ordered validations · 6 roles (3 opaque, 3 entity_backed).

## Coverage audit

§1.8: 9 rule_id blocks / 22 instances. §1.9: 72 instances (55 with full recipes, 17 `excluded_because` stubs), all nine required sections present:

| §1.9 section | recipes + stubs |
|---|---|
| Entities | 11 + 0 |
| State Machines | 10 + 5 |
| Calculations | 9 + 6 |
| Validations | 9 + 2 (all nine Table-4 rows incl. `satisfaction_pass`) |
| Endpoints | 6 + 0 (all six Table-5 rows) |
| Errors | 4 + 0 |
| RBAC | 3 + 1 |
| Cross-Cutting Complexity Layers | 2 + 3 (one instance per active layer) |
| Consistency Model | 1 + 0 |

- **All 66 error ids are triggerable** in §1.8/§1.9 (verified by scan; zero uncovered).
- Every stub's `excluded_because.difficulty_instance` resolves to a real §1.8 instance name (no §1.9 sibling citations); all 94 instance names unique across both files.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1360

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml consistency fixes found while writing §1.9

Nine in-place amendments were needed to keep the scaffold self-consistent (each applied with a uniqueness assertion + re-parse). The two made in this session:

- **Priority 10 auth check** demanded both `X-User-Role` and `X-User-ID` on every request, which contradicted the opaque-role convention used by ~1200 calls. It now requires `X-User-ID` only for the three entity_backed roles, and `ERR_UNAUTHENTICATED`'s catalog condition was widened to match.

Earlier ones (recorded for the record): relaxed `net_content_qty` to `>= 0` plus a zero-divisor guard in `unit_price_display` so `ERR_UNIT_PRICE_UNAVAILABLE` is reachable; re-routed zero-line audit closes from priority 40 to priority 63 so `ERR_AUDIT_SAMPLE_EMPTY` is reachable; corrected the header counts; split priority 76's `error_id` across the pay/deny paths; extended `ERR_FILE_INVALID_STATE`'s condition.

## Step 3: Copy shared files — 2026-09-04T11:41:55.909Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T11:56:46.295Z

Orchestrator truncation check (independent of the subagent's claim): `wc -l` = 556; tail shows the document ending on the final data row of the §5 error table (`| ERR_REFUND_NOT_APPROVED | 409 |`), a genuine section boundary — not mid-sentence, not mid-table. Heading scan confirms all of §1–§5 present with 20 `###` subsections. No regeneration needed.

Subagent summary (verbatim):

PRD generation is complete and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/workspace/PRD.md`

- **Final line count: 556**
- **Literal last section heading: `## 5. Error Code Catalogue`**
- Document ends at a genuine boundary — the final line is the last data row of the §5 table, `| `ERR_REFUND_NOT_APPROVED` | 409 |`. §4 has exactly 68 data rows, §5 exactly 66. No truncation.
- Structure: 5 `##` sections, 20 `###` subsections (11 in §2, 9 in §3).

## Verified coverage counts (all from SCAFFOLD.yaml, scripted)
| Item | Required | Covered |
|---|---|---|
| Entities | 15 | 15 |
| Endpoints | 68 | 68 (all 68 paths present verbatim in §4) |
| Error codes | 66 | 66 in §5 **and** all 66 also referenced outside §5 |
| Calculations | 12 | 12 (each rendered as a reconstructable prose formula) |
| State machines | 11 | 11 |
| Priority-ordered validations | 35 | 35 (§2.9 has exactly 35 numbered items; every scaffold priority number present) |
| Roles | 6 | 6 |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
- Entity fields: 148/148 present verbatim in backticks (0 missing)
- Endpoint body inputs: 88/88 (0 missing)
- Endpoint query parameters: 31/31 (0 missing)
- Path parameters: 1/1 (0 missing)

**Contract 2 — Rule Coverage: PASS**
- All 35 validation priorities and their error IDs are enumerated in §2.9 with condition prose, HTTP status, and full `applies_to` sets. (Six scaffold entries carry meta-placeholder error strings such as `ERR_<ENTITY>_NOT_FOUND`; the concrete codes those expand to are all named — verified individually for the stale-version trio, `ERR_AUDIT_SAMPLE_EMPTY`, `ERR_NOT_AN_OVERCHARGE`, `ERR_REFUND_NOT_APPROVED`, `ERR_DENIAL_REASON_REQUIRED` — with per-entity not-found codes in §2.10 and invalid-state codes in §3.)
- All 3 OCC rules in §2.8 with write endpoint, `expected_*_version` field, error ID, 412.
- All 11 state machines, their transitions, side effects, and cascades covered in §3; all 12 calculations stated as exact formulas with named constants.

**Contract 3 — §3 Path Purity: PASS**
- 875 backticked tokens scanned in §3; **0 violations** (no token starts with `/`, no bare HTTP method, no method+path combination).

## Fixes applied this pass
1. **Verification-script bug diagnosed, not a PRD defect.** The earlier mass-"MISSING" report was caused by the fenced ```json blocks in the verbatim §2.2 block desynchronizing backtick pairing for the entire remainder of the document. Stripping fenced blocks before extraction (`re.sub(r'```.*?```','',prd,flags=re.S)` then `` re.findall(r'`([^`\n]+)`') ``) reduced the miss set from hundreds of false positives to 2 genuine ones.
2. Added the two genuinely absent identifiers: `associate_id` in §3.5's audit-failure cascade (the created `AccountabilityAction`'s accountable-associate reference) and `regulatory_inspection_id` in §3.7 (taken from the path segment, not the body, on cascade-created findings).
3. Corrected the §3.4 daily-cap sentence typo — now reads "the four-hundred-and-eightieth minute is fine, the four-hundred-and-eighty-first is not".

The isolation constraint was honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no other `task_*` directory was read. All contract reports live only here in this message — nothing was written into PRD.md or any sibling file.

## Step 5: Generate unit tests — 2026-09-04T14:45:11.183Z

Launched concurrently with Step 6 in a single assistant message (physical isolation: `test_suite/` did not exist when the impl generator started). Orchestrator verified afterwards that `test_helpers/` and `test_suite/` sit at the task root and that no stray copies exist anywhere under `workspace/`.

Subagent summary (verbatim):

Final verification complete. Everything the task asked for is in place at the task root, nothing under `workspace/`.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/test_helpers/` — 9 files, 2888 lines
`__init__.py` 88, `api_client.py` 554, `api_errors.py` 164, `assertions.py` 316, `constants.py` 213, `factories.py` 399, `fixtures.py` 805, `test_users.py` 92, `types.py` 257

`/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/test_suite/` — `conftest.py` 49 + 14 test modules, 12811 lines total
`test_01_resource_shapes_and_listing.py` 566 (11 tests), `test_02_state_machines.py` 913 (10), `test_03_calculations.py` 981 (9), `test_04_validations.py` 1732 (9), `test_05_endpoints.py` 668 (6), `test_06_errors.py` 593 (4), `test_07_rbac.py` 490 (3), `test_08_cross_cutting.py` 601 (3), `test_09_variant_and_boundary_arithmetic.py` 839 (8), `test_10_combinatorial_formulas.py` 933 (6), `test_11_state_machine_and_cascade_depth.py` 1287 (8), `test_12_priority_and_cross_entity_gates.py` 1089 (8), `test_13_temporal_exclusion_windows.py` 1079 (6), `test_14_compensating_invariants.py` 991 (6).

## Gates

- `python3 -m py_compile` on all 24 emitted `.py` files: clean.
- `python3 -m pyflakes test_suite/*.py`: silent. (`test_helpers/__init__.py` emits only "imported but unused" for its deliberate re-export surface; no other helper warns.)
- Verbatim-quote checker over all 14 test modules: `0 bad quote(s)` each — every `PRD §x.y: "..."` citation survives a whitespace-normalized unique grep of `workspace/PRD.md`.
- `pytest test_suite --collect-only -q` → **97 tests collected**; per-file `def test_` count equals per-file `Design:` tag count in every module (one tag per test, no untagged and no dual-tagged tests).
- No stray `test_helpers/`/`test_suite/` anywhere under `workspace/`; `workspace/implementation/` never opened or written.

## Coverage audit

**Queue A — Difficulty (§1.8):** 22 instances across 9 rule_ids, 0 `excluded_because` stubs. **21 consumed at exactly 2 tests each = 42 tests.** Per rule_id tests: `boundary_precision_check` 4, `combinatorial_formula` 6, `compensating_invariant` 6, `cross_entity_state_dependency` 4, `dual_variant_calc` 4, `non_linear_state_machine` 4, `priority_pair_validation_conflict` 4, `resource_temporal_overlap` 6, `transitive_cascade` 4. Target >=2/instance met for every consumed instance.

**Queue B — Corner (§1.9):** 72 instances, 17 of them `excluded_because` stubs (correctly not translated). **All 55 non-stub instances consumed at exactly 1 test = 55 tests.** Per section: Entities 11, State Machines 10, Calculations 9, Validations 9, Endpoints 6, Errors 4, RBAC 3, Cross-Cutting Complexity Layers 2, Consistency Model 1. Target >=1/non-stub instance met with no instance over-served.

42 + 55 = 97, matching collection exactly. The audit found **zero unknown or malformed `Design:` tags** — every tag resolves to a real instance `name:` in its source yaml.

## Skipped instances

One, on the PRD-first two-condition filter:

- **`Difficulty/boundary_precision_check/unit_price_rounding_mode_decides_the_exact_half_cent_tie`** — the recipe builds two jurisdictions differing only in `unit_price_rounding` set to `ROUND_HALF_UP` vs **`ROUND_HALF_DOWN`**, and asserts 449.5 cents resolves to 450 vs 449. The PRD admits no half-down mode: §2.5 says `unit_price_rounding` "is either `ROUND_HALF_UP` (the default) or `ROUND_CEILING`", and §2.6 repeats "either half up or ceiling". The asserted outcome is therefore not uniquely derivable from the contract, so the instance was skipped outright — no weakened variant, no skip/xfail marker, no placeholder. (The other two `boundary_precision_check` instances are fully covered at 2 tests each; half-up-vs-ceiling rounding at the tie is exercised there.)

The 17 corner stubs are the only other gaps and are gaps by design.

## Fixture-correctness notes honoured

All money fields are emitted as JSON integers in cents (`new_retail_cents`, `shelf_price_cents`, `observed_shelf_price_cents`, `refund_cap_cents`, ...) — never strings. Per-role headers come from `build.manager(id)` / `build.associate_headers(id)` / `build.auditor(id)`, which stamp each distinct associate's own UUID as `X-User-ID`; no shared constant is used for entity-backed roles, and tests that span two stores mint separate manager/associate/auditor identities per store.

## Step 6: Generate implementation — 2026-09-04T14:45:11.183Z

Launched concurrently with Step 5 (same assistant message).

Subagent summary (verbatim):

Implementation complete and verified.

## Modules (`.../task_2707_shelf_label_price_accuracy_compliance/workspace/implementation/`)

| file | lines | contents |
|---|---|---|
| `core.py` | 687 | constants, enums, 66-entry error->status table, `ApiError`/`fail`, in-memory `DB`/`STATE`, logical clock, envelope + pagination builders, all body/query validators, OCC helpers |
| `routes_reg.py` | 585 | inspections, findings, response/adjudication 5-step settlement, refund claims, exception reports |
| `routes_audits.py` | 518 | scanner audits, scan lines, close/reopen, promo signage + sweep |
| `routes_estate.py` | 509 | jurisdictions, stores, aisles, associates, training, accountability actions, clock |
| `routes_files.py` | 501 | price-change files/lines, distribute, supersede, label tasks (print/place/verify) |
| `services.py` | 450 | derived-counter recomputation, posture chain, all cascade chains, label-serial minting |
| `views.py` | 324 | one serializer per entity, exact scaffold field sets, computed-at-read fields |
| `calc.py` | 253 | all 12 calculations (`Fraction`-based, single rounding) |
| `app.py` | 68 | blueprint wiring, envelope error handlers, `PORT` binding |
| `auth.py` | 53 | header auth ladder (10/20/22), `roles()` decorator |
| plus | | `requirements.txt`, executable `start.sh` (399 B) |

3948 lines of Python. `python3 -m py_compile` on all ten modules: COMPILE_OK. No `__pycache__`, no data files, no on-disk state.

## Coverage verified mechanically against SCAFFOLD.yaml
- **Endpoints 68/68** — `(method, normalized path)` extracted from `app.url_map` and from the scaffold, sorted and diffed: identical, zero missing, zero extra.
- **Error codes 66/66** — set-equal to `scaffold['errors']`, and every HTTP status matches (`status mismatches: []`). The 67th grep hit `ERR_XXX` is the envelope example on scaffold line 65, not a catalogue entry.
- **Entities 15/15, calculations 12/12, state machines 11/11, validations 35/35, roles 6/6** (3 entity-backed + 3 opaque).

## Smoke tests (port 39707, foreground `start.sh`, killed by exact PID each time)
Two independent end-to-end scripts, both **PASS** on a freshly launched process:
- Suite 1 (`SMOKE OK`) — clock, estate setup, training/certification, file->line->distribute->task->print/place/verify to `EXECUTED`, audit FAIL cascade (WRITTEN_WARNING, posture RESTRICTED), refund claim approve/pay, inspection chain (exposure 137500 -> waive 75000, OCC 412, REJECT escalation -> FROZEN, ACCEPT settlement liability 50 / credit 37 / assessed 74963), signage posture refusal, exception report with TRAINING_GAP suspension and closure gating, remedial retraining restoring CERTIFIED, envelope/pagination/not-found/schema contracts.
- Suite 2 (`SMOKE2 OK`) — signage post->amend->sweep NON_COMPLIANT->remove with posture returning to OPEN, expiry-beats-disclosure sweep ordering, label rejection loop (REJECTED + REPRINT_REQUIRED, serial cleared, second rejection auto-issuing a `system` COACHING, TASK_WEIGHTED score 50 -> SUSPENDED, print blocked while suspended), derived `overdue`, audit close PASS -> reopen (verdict nulled, `reopen_count` 1) -> re-close FAIL, aisle `last_audit_closed_at` stamp.

**Fresh-boot wipe confirmed**: after `kill <pid>` and relaunch, `GET /jurisdictions` and `GET /stores` both return `[]` with `total_count: 0`, and suite 2 — which had failed with `ERR_DUPLICATE_RESOURCE` against the dirty process — passed clean.

Two apparent failures during suite 2 were expectation bugs in my script, not implementation bugs, and each confirmed correct precedence: a duplicate label-task POST returns **412 `ERR_STALE_PRICE_CHANGE_FILE_VERSION`** rather than 409, because the first task moved the file `DISTRIBUTED -> PARTIALLY_EXECUTED` (bumping its version) and OCC at priority 45 outranks the duplicate check at 63.

Port 39707 has no listener remaining (`ss -ltn | grep -c :39707` -> 0). No pattern kills were ever used. Nothing under `test_suite/` or `test_helpers/` was read or written.

## Step 7: Run tests and iterate — 2026-09-04T15:16:37.125Z

Orchestrator independently verified the sweep artifacts rather than trusting the subagent's claim: all 8 `workspace/implementation/results.{1..8}.json` exist (timestamped 15:05) and each reports `passed=97 total=97 failed=0`.

Subagent summary (verbatim):

Clean 8-round parallel sweep: **97/97 passing in all 8 rounds** (results.1-8.json, 192s each, 97 tests collected per round).

## Iterations run
2 (sweep 1: 92/97 in every round, 5 deterministic failures; sweep 2: green).

## Tests deleted
None. All 5 failures passed STEP 1a coverage and STEP 1b unique-derivability — 2 were test bugs, 3 were implementation bugs.

## Fixes applied to `test_suite/`
No `test_helpers/` changes were needed; both test bugs were inline payloads in the test functions themselves.

- `/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/test_suite/test_13_temporal_exclusion_windows.py` — `TestAssociateLabourTouching::test_the_reservation_follows_the_assignee_across_files_until_the_task_turns_terminal` built a price-change line with `net_content_uom: "PT"`. PRD §3.3 enumerates the domain verbatim: "`net_content_uom`, one of `EACH`, `OZ`, `FL_OZ`, `LB`, `GAL` or `CT`". The PRD-faithful implementation correctly rejected it with `ERR_INVALID_REQUEST`; changed to `16 FL_OZ` (the uom is incidental — the test asserts closed-closed labour-interval conflicts, not unit price).
- `/home/ubuntu/github/CodingPRD/tasks/task_2707_shelf_label_price_accuracy_compliance/test_suite/test_09_variant_and_boundary_arithmetic.py` — `TestAccountabilityVariantDivergence::test_a_single_verified_placement_moves_only_the_task_weighted_denominator` looped twice reusing `file_number="PCF-1"`, so the second iteration hit `ERR_DUPLICATE_RESOURCE`. PRD §3.3: "a `file_number` (globally unique, 1 to 24 characters)" — the duplicate was the test's bug, not the implementation's. Parameterized the loop tuple with `PCF-1`/`PCF-2`.

## Fixes applied to `implementation/`
- `workspace/implementation/services.py`, `supersede_file()` — the withdrawal cascade only reset tasks already at `PRINTED`. PRD §3.3 is unconditional on the print axis: "For each withdrawn line, every label task on it whose placement axis is not `VERIFIED` has its print axis **forced** to `REPRINT_REQUIRED` with its `printed_label_serial` cleared." Now forces the reset for every non-`VERIFIED` task regardless of current print status. (Fixed both `test_12` and `test_14` failures. Note §3.4's passing cross-reference — "The same print-axis reset fires when a supersede withdraws the underlying line" — reads narrower, but §3.3 is the normative supersede spec and states the single condition explicitly, so it controls.)
- `workspace/implementation/services.py` — split `recompute_store()` into a pure `derive_store_counters()` plus a persisting `recompute_store()` and a new non-persisting `store_projection()`.
- `workspace/implementation/routes_estate.py`, `store_compliance_summary()` — the compliance-summary GET was calling `recompute_store()`, persisting the recomputed counters (and bumping `version`) as a side effect of a read, which healed the very drift the endpoint exists to expose. It now returns a live projection without writing. PRD §2.7 enumerates the posture-recompute triggers exhaustively (finding transitions, audit close/reopen, placement-axis transitions, signage transitions, refund settlement, file cascades, jurisdiction amendment — no read among them) and describes the endpoint as "the authoritative way to observe posture **drift**", which presupposes the stored projection stays stale.

## Notes
- No test was weakened, skipped, or xfailed; no `error_id` assertion was downgraded.
- Storage remains in-memory dicts only; no endpoints, fields, or side effects were added.
- Every sweep ran under `setsid nohup`; no round showed the `Terminated`/simultaneous-death reaping signature, and no broad pattern kills were used (the one smoke server was bound to port 39717 and killed by exact PID each time; 0 listeners remain).

Step 8 is NOT skipped: Step 7 ran 2 iterations with 3 `implementation/` fixes and 2 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-04T15:27:23.825Z

Orchestrator verified `workspace/PRD_FINALIZED.md` exists (123,702 bytes) and is NOT byte-identical to `PRD.md` (122,611 bytes) — correct, since Step 7 applied 3 implementation fixes.

Subagent summary (verbatim):

Done. Three surgical edits to `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 556 lines / 122,611 bytes
- `PRD_FINALIZED.md`: 556 lines / 123,702 bytes (**+0 lines, +1,091 bytes, +0.89%** by size; all three edits are in-paragraph)

## Changes
- **§2.7 (the derived gate, closing paragraph)** — *revise* — the compliance-summary read now explicitly re-derives the store's derived fields (backlog, posture, and every counter §2.7 names) from live data and **writes nothing**: stored counters, `compliance_posture`, `updated_at` and `version` are left as the last recompute trigger set them, so drift is exposed rather than healed; the plain store read and the store list (including its posture filter) report the stored values — `implementation/routes_estate.py:247-251`, `implementation/services.py:81-168`.
- **§3.3 (drafting a batch)** — *insert* — a duplicate `file_number` is refused with `ERR_DUPLICATE_RESOURCE`, checked after the body's references resolve — `implementation/routes_files.py:72-76`.
- **§3.4 (the never-requested move, end of the print/place/verify narrative)** — *revise* — the narrower cross-reference "The same print-axis reset fires when a supersede withdraws the underlying line" is replaced by the actual supersede semantics: every task on a withdrawn line whose placement axis is not `VERIFIED` is forced to `REPRINT_REQUIRED` with `printed_label_serial` cleared regardless of the prior print axis (including `NOT_PRINTED`), placement axis and stamps untouched — `implementation/services.py:313-333`.

## Per-edit pre-edit search log
**Edit 1 — §2.7 compliance-summary**
- (a) Subject: store derived counters / posture — where they are computed, persisted, and which reads see live vs. stored values.
- (b) Enumerated & read: `services.derive_store_counters` (81-155), `recompute_store` (158-161), `store_projection` (164-168), `recompute_stores` (171-175); every `recompute_store*` callsite (`routes_audits.py:290,319,447,469,510`; `routes_files.py:348,439,486,500`; `routes_reg.py:149,251,298,334,385,444,566`; `services.py:225,310,333,371`); `routes_estate.create_store` (195-223, initial zeros), `get_store` (226-229, stored row), `list_stores` (232-244, filters stored posture), `store_compliance_summary` (247-251); `views.store` (64-83, emits all 10 counters plus audit stamps); `core.apply_changes` (428-437, touch only on real movement). Also ran a scripted scan of every `@bp.get` handler for `apply_changes|touch(|recompute|insert(` — zero hits, confirming no read mutates anything. Auxiliary: `test_suite/test_08_cross_cutting.py:465-479` asserts the summary reads `RESTRICTED` live while the stored row stays `FROZEN` / `failed_audit_count_30d == 2`.
- (c) Adjustment: widened "recomputes the label backlog and the posture" to "the store's derived fields ... every counter named in this section", because the projection returns live values for all ten derived fields, not just two; scoped the non-persistence claim to this read only, and added the stored-value clause for the plain read/list so the sentence does not imply every read projects.

**Edit 2 — §3.3 duplicate `file_number`**
- (a) Subject: rejection code and ladder position for a repeated business key on price-change-file creation.
- (b) Enumerated & read: `routes_files.create_file` (63-90) — `req_*` schema parsing, then `must("jurisdictions", ...)` and `must("stores", ...)` for every scope id, then the global `file_number` scan -> `ERR_DUPLICATE_RESOURCE`; cross-checked PRD §2.9 priority 63 (which enumerates only four other endpoints) and the existing PRD precedents that do name the code (§3.5 scan-line `item_upc`, §3.6 `sign_code`).
- (c) Adjustment: kept the clause scoped to `file_number` alone rather than adding price-change-file creation to §2.9's priority-63 endpoint list, so no universal claim is made about the other unnamed uniqueness checks (`item_upc` in file, `aisle_code`, `employee_number`, `store_number`, jurisdiction `code`).

**Edit 3 — §3.4 supersede print-axis reset**
- (a) Subject: every code path that forces `print_status` to `REPRINT_REQUIRED` / clears `printed_label_serial`.
- (b) Enumerated & read (grep for `REPRINT_REQUIRED|printed_label_serial` across all modules): `services.suspend_associate:219` (guarded — `PRINTED` **and** placement != `VERIFIED`), `services.supersede_file:324-330` (unguarded on the print axis — any placement != `VERIFIED`, and skips lines already `VERIFIED`/`WITHDRAWN`), `routes_files.verify_placement:491-493` (rejection path, only when `PRINTED`), `routes_files.print_label:392` (accepts `NOT_PRINTED` or `REPRINT_REQUIRED` as source), `routes_files.create_label_task:337-339` (initial `NOT_PRINTED`). Auxiliary: `test_suite/test_12_priority_and_cross_entity_gates.py:686-704` asserts a never-printed task reads `REPRINT_REQUIRED` after supersede.
- (c) Adjustment: left the preceding suspension sentence verbatim (it is still exactly right for `suspend_associate`) and framed the new sentence as a *contrast* ("wider than the suspension one") scoped to lines the supersede cascade withdraws, so the wording does not bleed into the suspension or rejection resets; added "while the placement axis and its stamps are left exactly as they were" because `supersede_file` touches only the print axis, unlike `suspend_associate`.

Not patched (PRD already uniquely determines them; both were pure fixture bugs): the `net_content_uom` domain (`core.py:95` + §2.9 priority 25 -> `ERR_INVALID_REQUEST`), and the general "globally unique" property of `file_number` (only its error code was silent, which is edit 2).

Orchestrator decision for Step 9: the implementation is 3948 lines across 10 modules, which has historically caused a single-agent Step 9 to no-op (leaving PRD_COMPLETED.md byte-identical to its source). Step 9 will therefore be run as three SEQUENTIAL module-partitioned passes over one shared PRD_COMPLETED.md — pass 1 performs the `cp` from PRD_FINALIZED.md and covers core/auth/app/views; pass 2 covers calc/services/routes_estate; pass 3 covers routes_files/routes_audits/routes_reg. Passes 2 and 3 must NOT re-copy the file.

## Step 9: Complete PRD — 2026-09-04T15:56:03.305Z

Run as three SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from re-copying it). 66 hunks total, all in-paragraph.

Orchestrator verification: `PRD_COMPLETED.md` is 140,304 bytes and byte-differs from BOTH `PRD_FINALIZED.md` (123,702) and `PRD.md` (122,611) — the scan genuinely ran. Structure intact (5 `##`, 20 `###`); file still ends on the last row of the §5 error catalogue. Also confirmed no file under `implementation/`, `test_helpers/` or `test_suite/` was modified after the 15:05 green sweep, so the 8×97/97 result still describes the shipped code.

Size progression: PRD_FINALIZED 556 lines / 123,702 chars -> pass 1: 557 / 128,882 -> pass 2: 557 / 133,622 -> pass 3: 557 / 140,304.

### Pass 1 (core.py, auth.py, app.py, views.py) — 11 hunks: 3 mismatch, 8 ambiguity

- **§2.1 role/record agreement** — revise — mismatch — PRD claimed an `X-User-ID` naming no associate is `ERR_ASSOCIATE_NOT_FOUND` (404); impl folds nonexistent-actor and role-code-disagreement into one check reported as `ERR_ROLE_CODE_MISMATCH` (403) — `auth.py:22-25`
- **§2.2 error format** — insert — mismatch — new bullet pinning that framework-level failures carry `ERR_INVALID_REQUEST` at HTTP 404 (unrouted path), 405 (undeclared method), 400 (malformed) and 500 (unexpected fault), so it is the one identifier whose status is not fixed by §5; plus trailing-slash tolerance — `app.py:19,42-58`
- **§2.2 envelope bullets** — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` is read from real server time, not the logical clock — `core.py:323-337`
- **§2.3 pagination** — revise — ambiguity — "integer" means canonical decimal spelling: whitespace tolerated, but leading `+`, leading zero, decimal point, exponent and empty value all rejected — `core.py:636-655`
- **§2.3 ordering** — revise — ambiguity — `created_at` ties (the common case under a frozen clock) break by ascending insertion sequence — `core.py:467`
- **§2.3 filters** — revise — ambiguity — `overdue` accepts only lowercase `true`/`false`; id/business-key filters get no validation and match no rows rather than raising not-found — `core.py:668-680`
- **§2.4 audit triplet** — revise — mismatch — PRD said `version` increments per mutation; impl increments **once per mutating request** per record (two cascade hops onto one store = +1, not +2), and a derived/cascade write that moves no field touches neither `updated_at` nor `version` — `core.py:411-437`
- **§2.6 money and percentages** — revise — ambiguity — integral numeric results serialise as JSON integers (`2`, not `2.0`), applied to percentages, `net_content_qty`, `unit_price_display_cents`, `unit_price_basis_qty` — `core.py:377-385`, `views.py:20-22`
- **§2.9 priority 25 (schema)** — revise — ambiguity — timestamps accept `Z`/`z`/numeric offset and a bare zone-less form read as UTC; absent/empty body reads as `{}`; non-object JSON is a schema failure; explicit `null` is treated as omitted — `core.py:304-314,471-491`
- **§3.3 completion** — revise — ambiguity — `line_count`/`verified_line_count` are read-time projections, not stored, so they never drift and never move the file's `version` on their own — `views.py:121-123`, `services.py:251`
- **§3.5 error rates** — revise — ambiguity — `sample_size`/`overcharge_count`/`undercharge_count` are read-time projections: already non-zero on a `SCANNING` audit, don't bump the audit's version on append, and survive a reopen untouched — `views.py:191-194`, `services.py:375`

Pass 1 notes: the full `ERROR_STATUS` table was diffed mechanically against §5 — 66 vs 66 entries, zero name or status discrepancies. All 32 enum domains in `core.py` verified against §2.5/§3 prose: all already pinned uniquely. PORT/0.0.0.0 binding in `app.py:67-68` is governed by `INSTRUCTION.md`, not the PRD, so no PRD change was made for it.

### Pass 2 (calc.py, services.py, routes_estate.py) — 22 hunks: 3 mismatch, 19 ambiguity

Mismatches:
- §3.3 "Computing the printed unit price" — revise — mismatch — PRD said `unit_price_basis_qty` is "never rounded, to as many as six fractional digits"; impl quantises it half up to exactly six places — `calc.py:62`
- §3.2 suspension paragraph — revise — mismatch — PRD scoped the print-axis reset to tasks sitting at `PLACED`; impl resets *any* assigned task with print `PRINTED` and placement not `VERIFIED` (so `UNPLACED`/`REJECTED` tasks too) — `services.py:219-221`
- §2.9 priority 63 — insert — mismatch — ladder claimed uniqueness applies to only four endpoints; impl enforces the §3.1 estate keys (`code`, `store_number`, `aisle_code`, `employee_number`) at the same priority, ahead of the priority-67 store mismatch — `routes_estate.py:266-272, 342-346`

Ambiguity pins:
- §2.7 posture triggers — insert — every trigger runs the same *total* recompute of all nine counters, posture last — `services.py:81-155`
- §2.4 logical clock — revise — echo is a lone `current_utc` in `data`, UTC-normalised to 3 fractional digits; clock is non-monotonic — `routes_estate.py:502-508`
- §2.5 rulebook — insert — jurisdiction `name` is 1-255 chars — `routes_estate.py:158`
- §2.5 rulebook — revise — `signage_disclosure_codes` entries must be non-empty, no upper bound on length — `routes_estate.py:134-136`
- §3.1 amendments — insert — PATCH writes only named settings, `null` leaves the value untouched (does not reset to default), empty amendment succeeds without moving `version` — `routes_estate.py:73-150, 182-191`
- §3.1 amendments — insert — signage cascade sweeps every store of the jurisdiction, but since no sign `status` changes, no store counter/posture/`version` moves — `services.py:355-371`
- §3.1 aisles — insert — `assigned_associate_id` is required-but-nullable (omission is `ERR_INVALID_REQUEST`, `null` clears); a no-op re-assign doesn't touch the aisle — `routes_estate.py:320-329`
- §3.1 associates — revise — `employee_number` 1-64, `full_name` 1-255, and the three training fields start null — `routes_estate.py:338-361`
- §3.2 training inputs — insert — `module_code` 1-64 chars, `score_pct` 0-100 with <=2 decimals — `routes_estate.py:393-394`
- §3.2 training — insert — an accepted recording always bumps `version` even when nothing moved — `routes_estate.py:419, 435`
- §3.2 recertification — insert — a `CERTIFIED` associate recording below 80 is `ERR_ASSOCIATE_INVALID_STATE` and stores nothing — `routes_estate.py:422-423`
- §3.2 reinstatement — insert — the wrong-module test precedes the score test — `routes_estate.py:400-404`
- §3.2 ledger — insert — `issued_action_count` tracks the outstanding `ISSUED` set, not a lifetime tally — `services.py:190-196`
- §3.2 variants — insert — the governing `accountability_variant` is the associate's own store's jurisdiction, read at recompute time — `services.py:188`
- §3.2 suspension floor — insert — a non-`CERTIFIED` associate is never suspended by a recompute — `services.py:198-203`
- §3.2 direct actions — revise — `source_ref` 1-255 and null when omitted; `issued_by_ref` is null for a `ComplianceOfficer` who sent no `X-User-ID` — `routes_estate.py:446, 450`
- §3.2 void/complete — revise — whitespace-only `void_reason` counts as empty, max 500, stored verbatim, ignored on the `COMPLETED` path — `routes_estate.py:485, 490-494`
- §3.4 printing — revise — serial is `LBL-` plus a per-store sequence zero-padded to six digits, starting at 1, advancing on every print including reprints — `services.py:457-462`
- §3.5 failure cascade — revise — the cascade action's `source_ref` is the failing audit's `id` — `services.py:408`
- §3.9 ranking — revise — the stored two-decimal `error_rate_pct` is the sort key, not the unrounded quotient — `calc.py:226-232`

### Pass 3 (routes_files.py, routes_audits.py, routes_reg.py) — 33 hunks: 10 mismatch, 23 ambiguity

routes_files.py:
- §3.3 — insert — ambiguity — a repeated id inside `scope_store_ids` is a schema `ERR_INVALID_REQUEST`, not a duplicate-resource refusal — `routes_files.py:70`
- §3.3 — insert — ambiguity — `item_description` is 1-255 chars; `category_code` must arrive already uppercase (lowercase -> `ERR_INVALID_REQUEST`, not normalised) — `routes_files.py:124-125`
- §3.3 — insert — ambiguity — the four distribution gates are evaluated state -> at-least-one-line -> unit-price resolvability -> deadline — `routes_files.py:183-196`
- §3.4 — insert — ambiguity — a line belonging to another batch is `ERR_PRICE_CHANGE_LINE_NOT_FOUND`, resolved before the aisle/associate refs — `routes_files.py:264-265`
- §2.8 — insert — mismatch — the inspection/audit pins require integers >= 1 while `expected_price_change_file_version` has no lower bound (a pinned 0 there is a 412, not a 400) — `routes_files.py:259` vs `routes_reg.py:260,345`
- §3.4 — insert — ambiguity — "non-terminal" = placement axis != `VERIFIED`; the daily cap splits intervals at midnight and only tests days the new interval touches — `routes_files.py:230-246,313-324`
- §3.4 — insert — mismatch — the suspended-assignee refusal on print is evaluated last, after the file-state and posture gates, despite reporting the task's own invalid-state code — `routes_files.py:401-403`
- §3.4 — insert — ambiguity — `observed_shelf_price_cents` is required and >= 0 — `routes_files.py:419`
- §3.4 — insert — ambiguity — `ERR_LABEL_NOT_PRINTED` sits after the placement-axis state test and before the actor's store agreement — `routes_files.py:421-427`
- §3.4 — insert — mismatch — `rejection_reason` (<= 500, empty allowed) is validated then discarded; nothing stores it — `routes_files.py:448`
- §3.4 — insert — ambiguity — the 48-hour verification bound is strict — `routes_files.py:464-467`
- §3.4 — insert — ambiguity — the coaching action fires at exactly the 2nd rejection (never on the 3rd) and carries `source_ref` = task id — `routes_files.py:496-499`

routes_audits.py:
- §2.9 p51 — insert — ambiguity — opaque-role callers resolve to no associate, so the certification rule is skipped, not failed — `routes_audits.py:54-65`
- §2.7 — revise — mismatch — posture gating is at **four** write points; `ROUTINE` audit creation is the fourth — `routes_audits.py:86-87`
- §2.9 p52 — revise — mismatch — same, in the ladder entry (four endpoints, audits only when `ROUTINE`) — `routes_audits.py:86-87`
- §2.9 p40 — revise — mismatch — every non-`CLOSED` audit (`OPEN`/`SCANNING`/`REOPENED`) accepts scan lines — `routes_audits.py:176-177`
- §3.5 — insert — mismatch — `reopen_reason` is required 1-500 chars but is not persisted — `routes_audits.py:298`
- §3.6 — insert — ambiguity — `disclosure_codes` is required, may be empty, unbounded above, distinct, non-empty entries — `routes_audits.py:333`
- §3.6 — insert — mismatch — the posting posture gate is reached before the disclosure test — `routes_audits.py:427-437`
- §3.6 — revise — mismatch — the sweep recomputes once after the whole walk (even when nothing moved), and `swept_count` counts every non-removed sign including `DRAFT` — `routes_audits.py:480-517`
- §3.6 — insert — ambiguity — removal leaves `missing_disclosure_codes` as it stood — `routes_audits.py:461-468`

routes_reg.py:
- §3.7 — insert — ambiguity — `inspector_ref` 1-255; the evidence audit need not be `CLOSED` at logging time — `routes_reg.py:52-55`
- §3.7 — revise — mismatch — `ERR_FINDINGS_EMPTY` is reached only after both state gates; a non-array `findings` is `ERR_INVALID_REQUEST`; `affected_aisle_code` is 1-8 chars — `routes_reg.py:104-127`
- §3.7 — insert — ambiguity — `remediation_action_code` 1-64, `remediation_evidence_ref` 1-255 — `routes_reg.py:185-186`
- §3.7 — insert — mismatch — on `REMEDIATED` the stored action code satisfies the requirement when the body omits it — `routes_reg.py:214-215`
- §3.7 — insert — ambiguity — waiver: whitespace-only reason refused, <= 500 chars, and a `CLOSED` inspection yields `ERR_INSPECTION_INVALID_STATE` before the reason test — `routes_reg.py:229-234`
- §3.7 — insert — ambiguity — a direct `target_status` `ESCALATED` passes schema then always fails `ERR_FINDING_INVALID_STATE` — `routes_reg.py:182-183,245-246`
- §3.7 — insert — ambiguity — `remediation_summary` 1-2000 — `routes_reg.py:259`
- §3.7 — insert — mismatch — `rejection_note` (<= 500) is discarded, and an override sent with `REJECT` is ignored with its ceiling never evaluated; override is an integer >= 0 and may equal the exposure — `routes_reg.py:285-299`
- §3.8 — insert — ambiguity — `customer_ref` 1-128 — `routes_reg.py:344`
- §3.8 — revise — mismatch — settlement has **no** per-branch role split; either authorized role drives any branch; `denial_reason` <= 500 and whitespace-only is refused — `routes_reg.py:412-443`
- §3.9 — insert — ambiguity — `audit_count`/`scan_line_count` are frozen at generation, not re-derived — `routes_reg.py:496-497`
- §2.9 p50 + §2.11 — revise — mismatch — the remediation SoD test keys on the audit's `auditor_associate_id`, not on who closed it — `routes_reg.py:548`
- §3.9 — insert — ambiguity — the qualifying-audit set is re-derived from the stored period at assignment time — `routes_reg.py:544-546`
- §3.9 — insert — ambiguity — the `TRAINING_GAP` action carries `source_ref` = report id; `closure_note` 1-2000 — `routes_reg.py:563,574`
- §2.9 p63 — revise — mismatch — exception-report uniqueness is per store-and-period regardless of status (a `CLOSED` report still blocks) — `routes_reg.py:475-481`

Pass-3 integrity checks: pass 1's `ERR_ROLE_CODE_MISMATCH` wording present 3x; pass 2's `LBL-` six-digit serial wording present; §4 still 68 data rows, §5 still 66; 5 `##` / 20 `###` headings unchanged.

PIPELINE COMPLETE — `workspace/PRD_COMPLETED.md` written.
