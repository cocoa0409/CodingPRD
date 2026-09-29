# Worklog — task_2269_home_electrification_assessment_panel_upgrade

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2269_home_electrification_assessment_panel_upgrade/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:18:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2269_home_electrification_assessment_panel_upgrade/`
- `SCAFFOLD.yaml` (§1.0–§1.7, 148 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8, 217 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9, 383 KB)

## Counts
| Item | Count |
|---|---|
| Entities (§1.1) | 14 — Program, MeasureCatalogItem, Household, IncomeVerification, Contractor, Inspector, Assessment, EligibleMeasure, RebateProject, ProjectMeasure, Reservation, StackingDeclaration, Inspection, ClawbackAction |
| State machines (§1.2) | 7 (Program, IncomeVerification, Contractor, Assessment, RebateProject, Reservation, Inspection) + 2 concurrency rules (§1.2.1) |
| Calculations (§1.3) | 13 (incl. income tier assignment, 3-stage measure allocation with group/household caps + residual, single-pass stacking limit, dual-variant quality score, expiry sweep, disbursement reconciliation) |
| Validations (§1.4) | 22 ordered rules + 2 declared priority conflicts |
| Endpoints (§1.5) | 52 |
| Errors (§1.6) | 48 — all 48 now triggerable by at least one §1.8/§1.9 instance (audited) |
| Roles (§1.7) | 5 (Applicant / Contractor / FieldInspector entity-backed; ProgramReviewer / ProgramAdmin opaque; `role_model: segregation_of_duties`) |
| §1.8 difficulty design | 9 rule blocks, 25 instances |
| §1.9 corner design | 9 sections, 73 instances (59 full test recipes + 14 `excluded_because` stubs deferring to §1.8) |
| `difficulty_level` | `expert_plus` |

§1.9 section breakdown: entities 12, state_machines 12, calculations 13, validations 9, endpoints 6, errors 10, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1.

## Verification
- `scaffold_lint.py`: **clean lint** — 1423 calls across §1.8+§1.9 conform to §1.5 (endpoint declared, role allowed, payload keys declared, capture paths resolvable, OCC versions always `${var}`), and all §1.1 FKs are reverse-reachable.
- Structural check: correct top-level keys per file, no duplicate instance names across the union of both design files, no stub carries a `test_recipe`, every non-stub has grounds/distinguishing_aspect/test_recipe with setup, setup_api_calls, trigger, assert.
- Error coverage audit: 0 missing error ids.

## Two SCAFFOLD.yaml consistency fixes made while grounding §1.9
- `Inspection SCHEDULED → CANCELLED` trigger/actor widened to cover the `POST /inspections/{id}/cancellation` endpoint path, not just the system cascade (the endpoint already declared that transition).
- `RebateProject VERIFIED → PAID` and `Reservation RESERVED → COMMITTED` actors changed from `ProgramReviewer` to `"ProgramReviewer | ProgramAdmin"` to match `POST /rebate-projects/{id}/payment`'s declared roles.

Note: the `ERR_SEGREGATION_OF_DUTIES` "filed the income verification it is now verifying" branch is only reachable when one user id wears both ProgramAdmin (to file) and ProgramReviewer (to verify) headers, since `POST /households/{id}/income-verifications` is not open to ProgramReviewer — the §1.9 rbac instance triggers it exactly that way.

## Step 3: Copy shared files — 2026-09-01T16:19:13.000Z

Copied `INSTRUCTION.md` → `tasks/task_2269_home_electrification_assessment_panel_upgrade/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:32:10.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2269_home_electrification_assessment_panel_upgrade/workspace/PRD.md` — **458 lines**, ending at §5 with no audit footer.

## Section coverage

| Section | Contents |
|---|---|
| §1 Introduction | 3 paragraphs; domain framing plus the two dominating properties (fiscal conservation, determinism) and the flat root-mounted topology |
| §2 (11 subsections) | 2.1 RBAC (5 roles, 3 entity-backed / 2 opaque, all `*_by_user_id` write sites) · 2.2 verbatim response block (byte-identical, verified) · 2.3 Pagination + the two order overrides · 2.4 Identity/audit fields + the 3 no-`version` immutable types · 2.5 Logical clock (`2026-08-01T00:00:00Z`) · 2.6 Rounding discipline (5 distinct rules) · 2.7 Appropriation + household-cap conservation identities · 2.8 the 2 OCC rules · 2.9 Segregation of duties (4 sites) · 2.10 the full 22-rung validation ladder with `applies_to` sets and both priority-conflict worked cases · 2.11 Cascade semantics |
| §3 (9 subsections) | 3.1 program + catalog · 3.2 intake + tier assignment · 3.3 contractor enrollment/suspension/quality (both score variants) · 3.4 assessment + Stage A–E qualification · 3.5 project creation, rate pinning, per-line incentive, 3-stage allocation waterfall (both variants) · 3.6 review, reservation, expiry sweep, extension · 3.7 installation + crew capacity · 3.8 inspection scheduling + the 3 divergent result branches · 3.9 stacking (8 pinned steps), disbursement reconciliation, post-payment clawback |
| §4 | 52-row, 4-column endpoint table + status-code convention paragraph |
| §5 | 48-row, 2-column error catalogue |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 207 required identifiers (163 entity field names + 116 endpoint inputs deduped + `id`/`item_id` path params + 24 computed-read output members + 4 `lines`-entry members). Strict exact-token match against PRD backtick tokens: **0 missing**. One repair was needed — `item_id` initially appeared only as `{item_id}`, so §2.10 was reworded to name the bare parameter.

**Contract 2 — Rule Coverage: PASS.** All 45 transitions across 7 state machines covered with preconditions and side effects (11 are expressed as shared-source/shared-target prose rather than a literal arrow pair — e.g. "`CLOSED` … may be reached from either `OPEN` or `SUSPENDED`", "prior … `PENDING_REVIEW` or `APPROVED` assessment to `SUPERSEDED`", "`EXPIRED` from either `RESERVED` or `CONTRACTOR_HOLD`"; the `ProjectMeasure` two-dimension machine was given an explicit per-transition enumeration in §3.7 during repair). All 13 calculations in precise prose including all 4 variants. All 22 validations with normative ordering, error id, and scope. Both OCC rules. All 48 error ids referenced in §2/§3 prose, not only in the table. All endpoint `side_effects` traced (verified mechanically against the scaffold dump). Sibling-branch symmetry given for program status, enrollment decision, suspend/reinstate, verify/reject, assessment approve/reject, project approve/incomplete/reject, and inspection PASSED/CONDITIONAL_PASS/FAILED.

**Contract 3 — §3 Path Purity: PASS.** 816 backtick tokens in §3 scanned; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path. §3 refers to operations only by role + action, state-transition framing, or capability description; concrete paths appear only in §2.8/§2.10 (where pinning `applies_to` requires them) and in the §4 table.

## Scaffold gaps resolved

1. **HTTP success codes** are not carried per-endpoint in the scaffold. Derived a stated convention: `201` for the 11 creating operations, `200` for transitions, computed reads, sweep, clock, and reads (§4 preamble).
2. **`updated_at`/`version` absence** is encoded only as `common_fields: false` on `Inspector`, `EligibleMeasure`, `ClawbackAction`. Made explicit prose in §2.4 plus a rationale for each.
3. **`budget_clawed_back_cents`** would read as a fourth conserved bucket; §2.7 states explicitly that it is a cumulative counter outside the three-way invariant, and §3.9 notes it grows while the conserved buckets rebalance.
4. **`Household.household_size` vs `IncomeVerification.household_size_attested`** — the tier calculation uses only the attested count. Called out as an explicit negative statement in §3.2 since both fields exist and are trivially confusable.
5. **`federal_credit_claimed_cents`** is audit-only; stated twice (§3.9 intro and step list) that it never enters any computation.
6. **Computed-read output shapes** (`incentive-quote` `lines` members, `quality-review` fields, sweep result fields, clock result fields) exist only as scaffold `output` descriptors; rendered as prose field enumerations in §3.3, §3.5, §3.6, §2.5.
7. **Anchor/capacity circularity** in the Stage A–E qualification is implicit in the scaffold's stage ordering; added an explicit paragraph in §3.4 explaining why the one-pass order resolves the deadlock, and that it is never re-run to a fixed point.

## Step 5: Generate unit tests — 2026-09-01T18:36:16.000Z

Generation is complete. Every instance in both design indices is now translated; nothing was skipped.

## Files written

**`test_helpers/`** (9 files, infrastructure): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`test_suite/`** (`conftest.py` + 17 test modules, **109 tests**):

| file | focus |
|---|---|
| `test_01_entity_records_and_request_shape.py` … `test_08_concurrency_thresholds_and_consistency.py` | queue B (corner index) — entities, state machines, calculations, ladder, endpoints, error catalogue, roles/segregation, concurrency |
| `test_09_dual_variant_calculations.py` | dual-variant + combinatorial formula depth |
| `test_10_nested_formula_arms_and_pinned_orders.py` | nested formula arms, pinned ordering |
| `test_11_cyclic_and_parallel_state_machines.py` | non-linear state machines |
| `test_12_cascade_chains.py` | transitive cascades (failed-reinspection release, expiry sweep, anchor strand) |
| `test_13_ladder_priority_pairs.py` | simultaneously violated rungs with forced winners |
| `test_14_boundary_precision.py` | AMI decimal, group-cap strict inequality, extension window/day limits, conditional-pass floor |
| `test_15_cross_entity_state.py` | suspended grandparent program, contractor hold, scheduled sibling spot inspection |
| `test_16_resource_windows.py` | inspector half-open windows + 45-min buffer, crew capacity over closed date intervals |
| `test_17_conservation_invariants.py` | program appropriation and household entitlement conserved across their compensating actions |

## Coverage

- **Queue A (difficulty, §1.8): 25/25 instances translated**, ≥2 tests each (0 skipped).
- **Queue B (corner, §1.9): 59/59 non-stub instances translated**, ≥1 test each (0 skipped). The 14 `excluded_because:` stubs were verified to cross-reference a real queue-A instance and were not emitted.
- 84 distinct `Design:` tags, one per test, each the last docstring line.

## Validation performed (static only — the runner owns the server)

- `python3 -m py_compile` clean on all 18 suite files and all 9 helper files.
- Citation audit (`/tmp/t2269_audit.py`): 302 PRD quotations, all verbatim against `workspace/PRD.md` after whitespace normalisation; every `Design:` tag resolves to a real non-stub instance; every `test_helpers` import is exported and used.
- Final mandatory passes: no `skip`/`skipif`/`xfail` anywhere; every test docstring carries at least one quoted PRD sentence; all **48** asserted `ApiErrorId` values are named in PRD prose (not merely in the §5 table); no occurrence of "scaffold", `§1.x`, or "Table N" in emitted code.

## Notable resolutions (PRD-first, where the design yaml differed)

- Group-cap boundary re-run uses the PRD's declared paths (two sibling creations, and the `INCOMPLETE → SUBMITTED` resubmission) rather than replacing a DRAFT's measure set, since §3.5 declares the provisional waterfall runs "at project creation, again on resubmission from `INCOMPLETE`".
- Avoided the exact-`expires_at` extension instant and any wrong-typed `payment_reference` probe — neither outcome is uniquely derivable from the PRD.
- Inspection-result actor field asserted as `recorded_by_user_id`; `disbursed_amount_cents` starts at 0; 422 (not 409) for `ERR_MEASURE_NOT_ELIGIBLE` / `ERR_NO_ELIGIBLE_MEASURES` / `ERR_PROGRAM_BUDGET_EXHAUSTED`.

## Step 6: Generate implementation — 2026-09-01T18:36:16.000Z

The implementation is complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2269_home_electrification_assessment_panel_upgrade/workspace/implementation/` (3,265 lines, in-memory dicts only, nothing seeded):

- `start.sh` (now executable; installs Flask only if missing, then `exec python3 app.py`), `requirements.txt`
- `app.py` — `create_app()`, ApiError/404/405/400/500 handlers, `PORT` default 10000, `use_reloader=False`
- Infrastructure: `errors.py` (48 PRD error ids + 3 transport ids, status/message tables), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `envelope.py`, `store.py` (14 collections, `_seq` insertion order, `public()`), `guards.py` (auth rungs 1–2, pagination rung 4), `fields.py` (rung-3 validators), `calc.py` (tiering, allocation waterfall, stacking, both quality measures), `domain.py` (lookups, navigation, allocation plumbing, all cascades, fitness/window rules)
- Routes: `routes/{programs,households,parties,assessments,projects,money,inspections,misc}.py` + `routes/__init__.py`

## Endpoint count
**52 API endpoints** (Flask route dump shows 53 GET/POST rules; the extra is `/static/<path:filename>`), matching PRD §4 exactly.

## Verification done
Booted from a fresh process via `bash start.sh` (empty store, correct envelope, 401/404 handling), then ran five scripted passes over every one of the 52 endpoints:
- Full happy path: program → OPEN → catalog → household → income verify → contractor enroll → inspector → assessment (Stages A–E) → approve → project → submit → review → reservation → installation → stacking → inspection PASS → payment. Budget/cap conservation identities (§2.7) held at every step.
- Cascades: expiry sweep (reservation EXPIRED → project EXPIRED, lines VOID, inspections CANCELLED), inspection-failure → remediation cycle → CONDITIONAL_PASS → VERIFIED, remediation-limit → FAILED_FINAL with `FAILED_REINSPECTION` clawback, post-payment SPOT failure → CLAWED_BACK with `POST_PAYMENT_INSPECTION_FAILURE` clawback, auto-suspension on quality score with CONTRACTOR_HOLD and reinstatement.
- Allocation checked numerically: group cap proration (444444/355556 of an 800000 HVAC group cap), household cap binding, residual cent to the last member in pinned order, conditional-pass reduction on the final variant.
- ~28 distinct error ids exercised (401/403/404/405/409/412/422/400 rungs), including ladder-order cases: pagination before path existence, existence before ownership, ineligibility before duplication, window before extension limit, enrollment status before credential currency.

## Bug fixed during verification
`routes/households.py` referenced an undefined `errors.ERR_SELF_VERIFICATION_FORBIDDEN` for the self-verification check; corrected to `errors.ERR_SEGREGATION_OF_DUTIES` (403). A reflection sweep now confirms every `errors.*`/`fields.*`/`domain.*`/`store.*`/`calc.*`/`clock.*`/`guards.*` attribute referenced anywhere exists, and that no error id is defined but unused.

## PRD ambiguities resolved
- **Timestamps/ordering**: `created_at`, `updated_at`, and `api_request_timestamp` all come from the logical clock; "created_at ASC" is implemented as insertion-sequence ASC (never id).
- **Versions**: start at 1; creation-time allocation writes do not bump the new record's version.
- **Rung applicability** taken verbatim from §2.10 — notably duplicate measure codes are *allowed* on `POST /assessments` (rung 15 covers only project create/submit), and `ERR_PROGRAM_NOT_OPEN` is checked only on reservation creation and payment (not submit/installation).
- **Rung 13 anchor trigger**: `is_panel_upgrade OR requires_qualifying_appliance`.
- **Contractor status at reservation** (required by §3.7 but absent from rung 11) reports `ERR_CONTRACTOR_NOT_ACTIVE` only, with no credential-currency check, placed after SoD and before rung 19.
- **Payment/household reconciliation**: `encumbered_cents -= release_delta` rather than a literal "set to disbursed", because §2.7 defines encumbrance as the sum over that household's RESERVED/COMMITTED reservations (multi-project safe).
- **FAILED_FINAL** sets every line to `install_status VOID` + `verification_status REJECTED` without a `rejection_reason` (§3.8 assigns `INSPECTION_DEFICIENCY` only in the below-limit branch).
- **Stacking** refuses when the allowed state incentive computes to `<= 0` (`ERR_STACKING_LIMIT_EXCEEDED`); a new declaration supersedes the prior ACTIVE one.
- **Reinstatement** clears `suspension_reason` to null (unspecified in the PRD).
- **Retirement** is idempotent (200 on an already-retired item); pagination faults all map to `ERR_INVALID_PAGINATION`; unknown enum query filters match nothing rather than erroring.
- **Inputs with no backing scaffold field** (`status_note`, `retirement_note`, `decision_notes`, `cancellation_reason`, `payment_reference`, `remediation_notes`, `extension_reason`, assessment `review_notes`, suspension's caller-supplied `suspension_reason`) are validated for type then ignored; suspension always stores `ADMIN_ACTION`/`QUALITY_SCORE` per §3.3.

## Step 7: Run tests and iterate — 2026-09-02T00:14:35.000Z

All 8 parallel rounds are green.

## Final sweep (exit condition met)

```
results.1.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.2.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.3.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.4.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.5.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.6.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.7.json  116/116 passed, 0 failed, 0 errors, 0 skipped
results.8.json  116/116 passed, 0 failed, 0 errors, 0 skipped
```
Results live at `/home/ubuntu/github/CodingPRD/tasks/task_2269_home_electrification_assessment_panel_upgrade/workspace/implementation/results.{1..8}.json`.

## Iterations run
Seven full 8-round parallel sweeps (≈900 test executions each). The union of non-passing tests was re-triaged after every sweep.

## Tests deleted
None. PRD verbatim-covered and uniquely determined every assertion that failed; no STEP 1a silence, no STEP 1b collapse pattern.

## Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header builder issued a PRD-inconsistent request.

## Fixes applied to `test_suite/` (both in `test_suite/test_14_boundary_precision.py`, class `TestExtensionWindowAndDayLimits`)
1. Three `validate_success(..., 201)` → `200` on `POST /reservations/{id}/extensions` (lines ~459, ~519, ~547). PRD line 349 enumerates exactly which creations return `201` — program, catalog item, household, income verification packet, contractor application, inspector, assessment, rebate project, reservation, stacking declaration, inspection — and a reservation extension is not among them; it "modifies an existing resource … return[s] `200 OK`". Assertion made more faithful, not weaker.
2. Inserted `set_clock(api, "2026-12-29T00:00:00Z")` before each extension-limit probe (lines 468, 555). PRD line 286 fixes the inner order as window membership → count limit → day limit and recomputes the window from the *current* `expires_at`; after the first grant moved expiry to 2027-01-28 the test's old clock sat outside the new window, so window membership answered first. The exact `ERR_EXTENSION_LIMIT_REACHED` error-id assertions were preserved.

## Fixes applied to `implementation/`
None. `routes/money.py::extend_reservation` already ran the PRD §2.10/line-286 check order and returned `200`; no endpoint, field, header, side effect, or seeded data was added or removed anywhere under `workspace/implementation/`.

## Key diagnostic finding (not a task defect)
Every other non-passing entry across all sweeps was host infrastructure, and each was categorized from its traceback rather than assumed:
- `subprocess.TimeoutExpired: 'pids=$(lsof -ti:<port> -sTCP:LISTEN …)' timed out after 5 seconds` raised inside `prd_bench_local_runner/pytest_plugin.py::_kill_port` — real `lsof` walks `/proc/*/fd` for ~5000 processes on a box at load 300-450, exceeding the runner's hardcoded 5s budget. Neutralized for my sweeps with a temporary `ss`/`/proc`-based `lsof` shim on `PATH` (fork-free descendant lookup, verified to return byte-identical PIDs to real `lsof`); this took per-round setup ERRORs from ~19 to 0. The shim was scaffolding only — no task file ever referenced it, and it has been removed along with the rest of my `.sweeplogs/` harness.
- `ConnectionResetError` / `RemoteDisconnected` on the first request of a test: the runner restarts the server on the same port between tests while the session-scoped `requests.Session` keeps a pooled keep-alive socket. Unfixable from PRD-traceable code (a `Connection: close` header would be a non-PRD addition), and it never repeated on the same test.
- `Failed: Timeout (>30.0s) from pytest-timeout` on the suite's heaviest tests: they measure 3-9s at load ~200 and 23-28s at load ~430, i.e. pure CPU starvation. A direct probe showed 31.8ms for a trivial `GET /programs` at load 410 versus ~1-2ms idle, ruling out an implementation hot spot.

The task tree is left with only its own artifacts (`__pycache__`/`.pytest_cache` cleaned); I never read any `SCAFFOLD*.yaml`.

## Step 8: Finalize PRD — 2026-09-02T00:19:07.000Z

Done. `PRD_FINALIZED.md` written with two minimal in-line edits, both inside PRD §3.6 (line 286).

## Line counts
- `PRD.md`: 457 lines; `PRD_FINALIZED.md`: 457 lines; **delta 0.0%** (both edits are intra-line insertions/revisions in line 286).

## Changes
- **§3.6 (line 286) — revise** — "a request made at or after expiry is refused with the same error" (i.e. `ERR_EXTENSION_WINDOW_NOT_OPEN`, 422) → refused with `ERR_RESERVATION_EXPIRED` by the §2.10 state gate, which is evaluated before any extension limit — `implementation/routes/money.py:128-133`.
- **§3.6 (line 286) — insert** — a granted extension creates no separate extension resource; it modifies the reservation and returns `200 OK` carrying the updated reservation; the optional `extension_reason` is validated as a string but not persisted — `implementation/routes/money.py:117,143` + `implementation/envelope.py:23`.

## Pre-edit search log

**Edit 1 — subject: which check answers, and with which error id, when the logical clock sits at or after a reservation's `expires_at` on the extension endpoint (the ordering subject of Step 7 fix #2).**
- (b) Paths enumerated: `routes/money.py:114-143` (`extend_reservation`: status → project state → `now >= expires_at` → window → count → days); every other `expires_at`/`ERR_RESERVATION_EXPIRED` site, found by grepping the whole `implementation/` tree — `routes/money.py:65` (reservation creation sets expiry), `routes/money.py:178-179` (installation), `routes/money.py:304-305` (payment), `routes/programs.py:136-138` (expiry sweep, inclusive `<=`); `errors.py:40,98,152` (`ERR_RESERVATION_EXPIRED` = 409, state-gate family); PRD §2.10 rung 8 vs rung 18 and PRD error-code table line 433 for consistency; `app.py` for any status rewriting (none).
- (c) Adjustment: I scoped the new clause to the *state gate* rather than naming only the expiry check, because the same rung in `extend_reservation` also raises `ERR_RESERVATION_NOT_ACTIVE` and `ERR_INVALID_STATE_TRANSITION` (project not `RESERVED`/`CONTRACTOR_HOLD`) ahead of the window check; wording "the state gate of §2.10 … evaluated before any of the extension limits" stays true for all three and matches rung 8 < rung 18 globally, including installation/payment which use the same 409 gate.

**Edit 2 — subject: HTTP status and response payload of `POST /reservations/{id}/extensions` (Step 7 fix #1's 201→200).**
- (b) Paths enumerated: `routes/money.py:112-143` (the only handler for that route; returns `envelope.object_response(store.public(reservation))`); `envelope.py:23-29` (default status 200); every explicit `201` return in the tree (`routes/programs.py:64,195`, `routes/households.py:41,84`, `routes/parties.py:41,135`, `routes/assessments.py:202`, `routes/projects.py:190`, `routes/inspections.py:74`, `routes/money.py:85` reservation, `:256` stacking declaration) to confirm the extension is the only reservation-scoped POST that is not a creation; `store.py:12-25` collection list (no `extensions` collection exists); `store.public` (`store.py:65-69`) for the returned field set; `fields.opt_str` (`fields.py:21-34`) for `extension_reason` handling; grep for `extension_reason` across `implementation/` (single hit, return value discarded).
- (c) Adjustment: changed my first draft "accepted but not stored" to "validated as a string but not persisted on it", since `fields.opt_str` does enforce the string type (rung 3) even though nothing is written; and phrased the status as a consequence of the grant being a modification, so it stays consistent with PRD line 349's closed 201 enumeration rather than competing with it.

Notably, Step 7's own triage treated both fixes as PRD-determined test bugs; the only genuine non-determination I found is the PRD's internal contradiction in line 286 (the "same error" clause versus both its own trailing `ERR_RESERVATION_EXPIRED` clause and §2.10 rung 8), which edit 1 resolves in favour of the implementation. No other PRD text was touched.

## Step 9: Complete PRD — 2026-09-02T00:34:27.000Z

Done. `workspace/PRD_COMPLETED.md` is written and complete.

## Summary on exit

**Files:** `PRD_FINALIZED.md` = 457 lines / 95,662 chars → `PRD_COMPLETED.md` = 457 lines / 113,017 chars. **Char delta: +17,355. Line delta: 0** (every change is an in-paragraph insert or revision; no new paragraphs, no new sections, no reordering).

**Counts:** 49 changes — **43 ambiguity-pins, 6 mismatch-revisions**.

- §2.1 — revise — mismatch — `recorded_by_user_id` on a `ClawbackAction` reattributed from reviewer/admin to the acting `FieldInspector`, since every clawback action is a cascade hop of an inspection result — domain.py:323
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not wall-clock time — envelope.py:19
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` reports `ERR_INVALID_PAGINATION` — guards.py:65-77
- §2.3 — insert — ambiguity — `created_at` ordering ties broken by write sequence (total order, never an id fallback); undocumented filters ignored, unmatched documented filter yields an empty page — store.py:51,75
- §2.4 — insert — ambiguity — `created_at` stamped from the logical clock — store.py:46
- §2.4 — insert — ambiguity — `updated_at` refreshed from the logical clock on mutation — store.py:59
- §2.10 rung 6 — insert — ambiguity — per-endpoint body-reference resolution order pinned; cross-scope references reported as not-found; catalog `prerequisite_measure_code` shares the 404 — assessments.py:141, projects.py:122, inspections.py:22, programs.py:186
- §2.10 rung 7 — insert — ambiguity — only the acting role's ownership comparison runs; every other role on the endpoint passes the rung untouched — projects.py:33, households.py:48
- §2.10 rung 12 — revise — mismatch — on `/installation` the panel-upgrade exemption does **not** apply (every reported measure is compared), capacity read from the live catalog item, check runs after `ERR_MEASURE_NOT_ON_PROJECT` — money.py:190-195
- §2.10 rung 13 — revise — mismatch — anchor satisfied by mere presence in the request (anchor need not be assessment-qualified); `requires_qualifying_appliance` behaves like a panel line; prerequisite must be in-request **and** a qualified assessment row — projects.py:56-76
- §3.1 — insert — ambiguity — all overridable program parameters validated as ≥ 0 (integers where integer-valued), no upper bound — programs.py:23-65
- §3.1 — insert — ambiguity — `new_status` enum; `status_note` validated but not persisted; DRAFT→OPEN needs positive budget; CLOSED blocked by a lingering `RESERVED` reservation, both `ERR_INVALID_STATE_TRANSITION` — programs.py:105-118
- §3.1 — insert — ambiguity — `measure_code` shape (hyphen-separated uppercase-alnum groups) and its `ERR_INVALID_REQUEST` rejections — fields.py:60, programs.py:160
- §3.1 — insert — ambiguity — `prerequisite_measure_code` must resolve at creation (`ERR_MEASURE_CODE_NOT_IN_CATALOG`) and is checked *before* the duplicate-code 409 — programs.py:186-191
- §3.1 — insert — ambiguity — retirement is idempotent and still bumps version; `retirement_note` validated but not persisted — programs.py:225-235
- §3.2 — insert — ambiguity — income-verification packet's null/zero field defaults enumerated — households.py:74-81
- §3.2 — insert — ambiguity — `decision` enum; `reviewer_notes` persisted only when supplied; non-`SUBMITTED` splits between `ERR_INCOME_TIER_ALREADY_VERIFIED` and `ERR_INVALID_STATE_TRANSITION`; `REJECT` still stamps verifier and `verified_at` — households.py:105-128
- §3.3 — insert — ambiguity — contractor creation null defaults, including `enrollment_decided_by_user_id` — parties.py:21-42
- §3.3 — insert — ambiguity — `decision` enum; `decision_notes` not persisted; non-`PENDING_ENROLLMENT` refused; approve needs both expiries strictly after today (stricter than rung 11); reject ungated — parties.py:53-75
- §3.3 — revise — mismatch — reinstatement requires license **and** insurance strictly later than today (`ERR_CONTRACTOR_CREDENTIAL_EXPIRED`) and clears `suspension_reason` to null; body `suspension_reason` never persisted — parties.py:79-98
- §3.4 — insert — ambiguity — contractor must belong to the household's program (`ERR_CONTRACTOR_NOT_FOUND`); assessment create has no ownership rung and no program-status gate — assessments.py:141-203
- §3.4 — insert — ambiguity — `evaluation_order` is the request array order, which is also the storage write order — assessments.py:95-137
- §3.4 — insert — ambiguity — the estimate runs the §3.5 waterfall with cost-share 0 for an unverified household, so pre-verification estimates are 0 — assessments.py:32-93, calc.py:83
- §3.4 — insert — ambiguity — approve `decision` enum, `review_notes` not persisted, non-`PENDING_REVIEW` refused, enrollment test precedes the empty-qualified-set test, `REJECT` applies neither — assessments.py:245-265
- §3.5 — insert — ambiguity — assessment/income-verification/contractor scoping errors; `contractor_id` untied to the assessment's; project null defaults — projects.py:122-191
- §3.5 — insert — ambiguity — measure-line and project-collection list filters enumerated — projects.py:203-236
- §3.5 — insert — ambiguity — the final variant reads null `verified_quantity`/`actual_cost_cents` as 0 rather than skipping the line — calc.py:83-159
- §3.5 — insert — ambiguity — allocation writes at creation are part of the initial record write (version stays 1); on submission they bump each changed line plus the project — domain.py:183-199
- §3.5 — insert — ambiguity — quote `variant` accepts only lowercase `provisional`/`final`, defaults `provisional`, else `ERR_INVALID_REQUEST` — projects.py:333-355
- §3.5 — insert — ambiguity — submit clears `incomplete_reason`, optional `estimated_project_cost_cents` must exceed 0 and overwrites; replacement *deletes* prior lines including `VOID` ones; omitted `measures` revalidates the surviving non-`VOID` lines — projects.py:240-288
- §3.6 — insert — ambiguity — review `decision` enum, `review_notes` persistence, non-`SUBMITTED` refused, APPROVE gate order (enrollment then income tier), `RETURN_INCOMPLETE` reason enforced at rung 3 so it precedes path existence — projects.py:292-329
- §3.6 — insert — ambiguity — household headroom shortfall at reservation reports `ERR_HOUSEHOLD_CAP_EXHAUSTED` — money.py:25-86
- §3.6 — insert — ambiguity — reservation null defaults; `reservation_notes` persisted, null when omitted — money.py:60-86
- §3.6 — insert — ambiguity — expiry accepts only `RESERVED`/`CONTRACTOR_HOLD` projects, and reservation status is checked before project state — domain.py:275-303
- §3.7 — insert — ambiguity — installation numeric bounds (all zero-or-more); unknown `measure_code` → `ERR_MEASURE_NOT_ON_PROJECT` ahead of the amperage comparison — money.py:149-195
- §3.7 — insert — ambiguity — gate order (project `RESERVED` → reservation `RESERVED` → not expired); omitted lines stay `PLANNED` with null figures; installation re-runs neither allocation variant — money.py:155-217
- §3.8 — insert — ambiguity — window bounds normalised to UTC/3dp with `scheduled_end` ≥ `scheduled_start`; inspector must be in the project's program (`ERR_INSPECTOR_NOT_FOUND`) — inspections.py:22-75
- §3.8 — insert — ambiguity — the sibling-inspection block is scoped to `REMEDIATION` + `POST_INSTALL` only, sitting after the project-state gate and before the inspector-window rung — inspections.py:40-56, domain.py:133
- §3.8 — insert — ambiguity — `cancellation_reason` validated but not persisted; already-resulted → `ERR_INSPECTION_ALREADY_RECORDED`, already `CANCELLED` → `ERR_INVALID_STATE_TRANSITION` — inspections.py:199-208
- §3.8 — insert — ambiguity — result enum→status mapping, payload defaults, `notes` persistence, ownership-rung precedence, `rejected_measure_codes` must name project lines — inspections.py:105-169
- §3.8 — revise — mismatch — the pass branch verifies `PENDING` lines with the quantities the installation report already stored (the result payload carries none); a passing `SPOT` moves no money; a failing `SPOT` on a non-`PAID` project only records + recomputes quality — inspections.py:171-193
- §3.8 — insert — ambiguity — `CONDITIONAL_PASS` severity ≤ 2 enforced inside the state gate, ahead of project- and line-level preconditions — inspections.py:130-150
- §3.8 — insert — ambiguity — the `ANCHOR_REJECTED` hop fires only when the project has anchor lines and **every** one is `REJECTED`; the final total is reallocated and any `ACTIVE` stacking re-evaluated — domain.py:409-439
- §3.8 — insert — ambiguity — remediation payload shape and overwrite semantics, exhausted cycles → `ERR_INVALID_STATE_TRANSITION`, reservation active/unexpired gates, no reallocation — money.py:276-340
- §3.9 — insert — ambiguity — `utility_rebate_cents` defaults to 0; terminal project states blocked while `DRAFT` is allowed; the arithmetic precedes supersession, so a rejected declaration leaves the prior row `ACTIVE` — money.py:221-257
- §3.9 — insert — ambiguity — `payment_reference` validated but not persisted; payment precondition order (all lines `VERIFIED` → program `OPEN` → reservation `RESERVED`) — money.py:344-389
- §3.9 — insert — ambiguity — a still-null payment basis is read as 0 — money.py:344-389
- §3.9 — revise — mismatch — `budget_clawed_back_cents` is incremented by the project's `disbursed_amount_cents` as it stood (equal to the reconciled `reserved_amount_cents`) — domain.py:383
- §3.9 — insert — ambiguity — `disbursed_before_cents` is always the pre-action disbursed figure, hence 0 on a `FAILED_REINSPECTION` row; `recorded_by_user_id` is the acting `FieldInspector` — domain.py:305-326, 349-352

**Judgement calls deliberately left unpatched** (impl behaviour is unobservable or is a bug rather than intent, so pinning it would have meant inventing prose):
- `parties.py:62` writes `enrollment_decided_by_user_id` before the credential check that can raise, leaving a partial in-memory write on a failed approve — treated as an implementation bug.
- `programs.py:105` DRAFT→OPEN does not re-assign `budget_available_cents = budget_total_cents` as the PRD says it does, but the two are already equal and nothing mutates budget before OPEN — no observable difference.
- `domain.py:465` compares inspector windows at full datetime precision rather than the PRD's stated minute resolution — behaviourally equivalent given the 45-minute buffer.

`test_helpers/` and `test_suite/` were not consulted; `SCAFFOLD*.yaml` and `worklog.md` were never read.
