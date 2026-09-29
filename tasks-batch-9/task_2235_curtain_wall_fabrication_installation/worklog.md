# Worklog — task_2235_curtain_wall_fabrication_installation

## Step 1: Create Task Directory — 2026-09-01T09:19:00.000Z

Created `tasks/task_2235_curtain_wall_fabrication_installation/` and `tasks/task_2235_curtain_wall_fabrication_installation/workspace/`.

## Step 2: Generate Scaffold — 2026-09-01T10:47:00.000Z

All three artifacts are complete and the lint is clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2235_curtain_wall_fabrication_installation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2235_curtain_wall_fabrication_installation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2235_curtain_wall_fabrication_installation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    81
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1587

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**
- `SCAFFOLD.yaml` (3265 lines) — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (4680 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (6681 lines) — single key `scaffold_corner_design`

All three parse with `yaml.safe_load`.

**Scaffold size**
| §1.1 entities | 15 |
| state machines | 13 (cyclic; incl. the two-axis InstallationZone and the REJECTED self-loop on AnchorEmbedSurvey) |
| OCC concurrency rules | 2 (`release-create-stale-package`, `breakage-draw-stale-glass-order`) |
| calculations | 10 (2 dual-variant: `zone_field_labor_cost`, `glass_procurement_risk_score`) |
| validations | 51 (priority 10 → 110) |
| endpoints | 81 |
| error catalog | 50 |
| RBAC roles | 8 (segregation-of-duties model: CWProjectManager, CWDetailer, DelegatedEngineer, ArchitectOfRecord, GlazingProcurement, StructuralContractor, FieldSuperintendent, QCInspector) |

**§1.8 — 24 instances across all 9 difficulty rules** (≥2 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2. Every assert literal was computed by executing the §1.3 formulas (e.g. labor 940800 vs 1149540, earned value 113178377/5658919/107519458, risk 70.00 exactly at threshold, mockup 781000→812240, thermal 5.84/7.34/7.49).

**§1.9 — 71 instances across the 9 claim-extraction sections**: entities 10, state_machines 15, calculations 13, validations 15, endpoints 5, errors 3, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1 — 54 full recipes plus 17 `excluded_because` stubs that defer to a named §1.8 instance. No name collides across §1.8 ∪ §1.9.

**Two reachability defects found and fixed in SCAFFOLD.yaml while authoring §1.9:**
- `ERR_DEFLECTION_LIMIT_UNSET` was unreachable at `POST /field-tests/{id}/record-result` (reaching PANELS_HUNG requires the system decision, so `system_type` can never still be UNDECIDED there, and priority 64 masks it). Moved validation 97 to `POST /installation-zones/{id}/field-tests` (scheduling a STRUCTURAL_DEFLECTION test before the L/240-vs-L/175 line exists) and moved the error id between the two endpoints' `errors:` lists.
- `ERR_ZONES_NOT_WEATHER_TIGHT` had an unreachable `triggered_by` (a zone in REMEDIATION also reverts the package out of WEATHER_TIGHT_ACHIEVED, so priority 60 masks 108). Rewritten to the reachable path: a new InstallationZone added to a package already in WEATHER_TIGHT_ACHIEVED — now exercised by the §1.9 instance `zone_added_after_weather_tight_blocks_close_out`.

No sibling task directory under `tasks/` was listed, read, or grepped at any point.

## Step 3: Copy Shared Files — 2026-09-01T10:42:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2235_curtain_wall_fabrication_installation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T11:03:00.000Z

PRD generated and audited.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2235_curtain_wall_fabrication_installation/workspace/PRD.md` — **485 lines**

## Structure
- **§1 Introduction** — 3 paragraphs framing the subcontractor's four-hat problem and stating up front that the retraction chain, not the happy path, is the hard part.
- **§2 Global Specifications** — 12 subsections: 2.1 Project Participants & RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and Collection Filtering · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Project Clock · 2.6 Path Resolution and Cross-Reference Integrity · 2.7 Units, Precision and Rounding Discipline · 2.8 Stale-Version Guards · 2.9 The Engineering Posture Gate · 2.10 Ledger Invariants and Derived-Field Reconciliation · 2.11 Two Independent Zone Axes and Cascade Semantics · 2.12 Order of Rejection.
- **§3 Business Logic & Workflows** — 9 subsections (170 lines): package/system fork · delegated design review cycle · mockup chambers and invoicing · glass procurement risk and breakage stock · fabrication release and shop movement · embeds, hoisting and install sequence · crew days and the two labor-cost faces · field tests, defects and weather-tight certification · earned value and close-out.
- **§4 Endpoint Definitions** — status-code paragraph + 4-column table, **81 rows**.
- **§5 Error Code Catalogue** — 2-column table, **50 rows**.

## Hard Contract reports

**CONTRACT 1 — FIELD-NAME COVERAGE: PASS.** 171/171 required identifiers (153 entity fields, 94 write-endpoint input fields, 30 query/path parameters; 171 unique) appear as backticked tokens in PRD.md. Missing: 0. Verified by mechanical diff against a set extracted from SCAFFOLD.yaml; one gap found on the first pass (`crew_day_id` appeared only as `{crew_day_id}`) and repaired, then re-run clean.

**CONTRACT 2 — RULE COVERAGE: PASS.** Six high-risk categories walked: (1) validation priority ordering — the full 51-row ladder from priority 10 to 110 rendered as an ordered 16-band list in §2.12, with the three counter-intuitive precedences called out explicitly (zone-sequence over panel-lot readiness, release admissibility over glass balance, open-critical-defect over billing ceiling); (2) both concurrency rules with `expected_package_version` / `expected_glass_order_version`, 412 codes, and the why-OCC-not-state rationale; (3) all cross-entity cascades — the 4-hop submittal-revision chain, the 2-hop glass-re-fire chain (gated on `risk_flag` flipping true), the 4-hop field-test-failure chain, plus all six package bubble-up/revert edges; (4) `applies_to` scopes enumerated per error code; (5) field-level types, defaults and initial values for all 15 entities, with `TestLab` explicitly flagged as carrying only `id` and `created_at`; (6) sibling-branch symmetry for the four-way review decision, UNITIZED/STICK_BUILT, NOMINAL/EXPEDITE_ADJUSTED, PROVISIONAL_FORWARD/FINAL_CHRONOLOGICAL, both certify edges, both survey-from-states and PASS/FAIL re-inspection. Tail verified mechanically: 13/13 state machines with every transition and terminal set, 10/10 calculations with exact constants and rounding positions, 81/81 endpoints present in §4, 50/50 error codes present in §5 with statuses matching the scaffold exactly and every code also narrated in §1–§3, all 8 roles named verbatim, all entity enum values present.

**CONTRACT 3 — §3 PATH PURITY: PASS.** 301 backtick tokens in §3; 0 tokens beginning with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. All operations in §3 are expressed as state transitions, role+action verbs, or capability descriptions.

## Two judgement calls worth flagging
- The scaffold's validation rows say "X-Role header absent"; SKILL.md mandates `X-User-ID` / `X-User-Role`. The PRD uses the mandated names, mapping absence to `ERR_MISSING_ROLE` (401), a non-permitted role to `ERR_UNAUTHORIZED` (403), and `ERR_MISSING_USER` (401) to the five operations priority 20 scopes.
- Field-test result recording requires `install_status == PANELS_HUNG` as a precondition, but priority 64's `applies_to` deliberately excludes that endpoint. I aligned strictly to the scaffold: §3.8 states the precondition and attributes it to `ERR_INVALID_STATE` (priority 60, also 409), and field tests are not listed in §2.12's priority-64 scope.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling `task_*/` directory was read. No audit report text was written into PRD.md or any sibling file.

## Step 5: Generate Unit Tests — 2026-09-01T13:20:00.000Z

Stage 2 is complete. All 78 non-stub design instances are translated; no instance was skipped.

## Files written

`tasks/task_2235_curtain_wall_fabrication_installation/`

- **`test_helpers/`** (Stage 1, 9 files, ~unchanged this session): `types.py`, `api_client.py` (~85 endpoint methods), `api_errors.py` (50 error IDs + `HTTP_STATUS_CODES`), `constants.py`, `test_users.py` (8 roles + malformed-header builders), `factories.py` (46 payload builders), `assertions.py` (ledger/envelope helpers), `fixtures.py` (atomics + 20 scenario entry points), `__init__.py`.
- **`test_suite/`** (18 files): `conftest.py` plus `test_01`–`test_09` (queue A) and `test_10`–`test_17` (queue B). New this session: `test_14_endpoints.py`, `test_15_errors.py`, `test_16_rbac.py`, `test_17_cross_cutting.py`; `test_11_state_machines.py` and `test_09_compensating_invariants.py` were corrected.

## Counts

- **117 test functions / 119 collected** (one `parametrize` with 3 cases), 9,516 lines total.
- Queue A: 48 tests / 24 difficulty instances (min 2 tests each).
- Queue B: 69 tests / 54 non-stub corner instances (entities 12, state_machines 14, calculations 9, validations 12, endpoints 6, errors 4, rbac 6, cross_cutting+consistency 6).
- The 17 corner stubs carrying `excluded_because:` were not translated, as required.

## Audit results (all clean)

- `python -m compileall` OK; `pytest --collect-only` collects 119; `pyflakes test_suite/*.py` clean.
- **Citations:** all 117 `PRD: "…"` quotes survive literal grep against `workspace/PRD.md` (two were fixed this session: an invented release-fan-out quote in `test_14`, and a titular one in `test_16` replaced with the rule-bearing defect-raising sentence).
- **Tags:** exactly one `Design:` line per test, always the last docstring line; no tag points at a stub or a non-existent instance. Fixed a real defect: all 14 `Design:` lines in `test_11_state_machines.py` had been written as `Corner/entities/…` instead of `Corner/state_machines/…`.
- No occurrence of "scaffold" or scaffold section references anywhere in `test_suite/` or `test_helpers/`.

## Deliberate assertion-level omissions (PRD-vs-design divergences)

Every instance is covered; these individual probes inside recipes were dropped or altered because the PRD does not uniquely derive the design's expectation:

- `endpoints/listings_filter_and_paginate…`: dropped `weather_status=FOG → ERR_INVALID_ENUM` — PRD §2.12 step 5 scopes enum validation to **write** endpoints.
- `endpoints/hang_panels_consumes_the_reservation…`: dropped the "hang with a CONSUMED reservation id" probe (needs a third anchored zone).
- `errors/hanging_outside_the_reserved_window…`: dropped "hang exactly at `window_end`".
- `rbac/shared_operations_accept_every_declared_role`: the design's `origin: ARCHITECT_REVIEW` is not a PRD enum value — used `PUNCH_LIST`; the role-sharing claim is unaffected.
- `rbac/exclusive_operations_are_denied…`: the "same call succeeds under its owning role" leg uses a **fresh** submittal for the seal (an APPROVED submittal's seal error is ambiguous between step 10 terminal and step 11 `ERR_SEAL_INVALID`); the other four owning-role calls assert the business error the role gate had masked (`ERR_INVALID_STATE`, `ERR_TERMINAL_STATE`, `ERR_ZONE_SEQUENCE_VIOLATION`, `ERR_LOT_NOT_FOUND`).
- Earlier sessions, unchanged: `state_machines/every_entity_starts…` asserts `received_lites == 0` (PRD line 233) against the design's `null`; `critical_defects_cannot_be_waived…` rebased on a certify-ready zone so `ERR_OPEN_CRITICAL_DEFECT` is reachable past the evidence gate; `validations/coating_revision_after_receipt…` drops the CLOSED-order probe (step 10 derives `ERR_TERMINAL_STATE` first); `deflection_failure_cascade…` drops the design's close-out `ERR_ZONES_NOT_WEATHER_TIGHT` probe (PRD derives `ERR_INVALID_STATE`); `entities/test_lab_row_is_immutable…` asserts no status code for undeclared PUT/PATCH/DELETE routes.

## Step 6: Generate Implementation — 2026-09-01T12:26:00.000Z

Both verification suites now pass and the HTTP boot path is confirmed. Final state:

## Implementation delivered

`/home/ubuntu/github/CodingPRD/tasks/task_2235_curtain_wall_fabrication_installation/workspace/implementation/`

| File | LOC | Role |
|---|---|---|
| `start.sh` | 10 | launcher (`exec python3 app.py`, `PORT` env, guarded flask install) |
| `app.py` | 63 | app factory, blueprint registration, `ApiError`/`HTTPException` handlers |
| `errors.py` | 159 | 50-entry error catalog + `ApiError` |
| `store.py` | 177 | in-memory dicts, logical clock, `base_row`/`apply`/`touch` versioning |
| `calc.py` | 278 | all 10 derived formulas (`Decimal` + ROUND_HALF_UP) |
| `validate.py` | 311 | auth, field specs, enum/range/window validation, query filters |
| `envelope.py` | 42 | meta/response_type/data envelope + pagination meta |
| `common.py` | 27 | `get_or_404`, `single`, `created`, `listing` |
| `domain.py` | 652 | serializers, posture re-derivation, all cascades, package sync |
| `routes_core.py` | 474 | packages, submittals |
| `routes_glass.py` | 474 | glass orders, releases, panel lots, breakage draws |
| `routes_zones.py` | 664 | zones, embed surveys, crew days, hoist rigs/reservations |
| `routes_qc.py` | 529 | labs, mockup tests, field tests, defect items |
| `requirements.txt` | 1 | `Flask>=2.3.0` |

**3,861 LOC total** across 14 files. Storage is in-memory only — no `sqlite`, `open()`, `json.dump`, `pickle` or `shelve` anywhere; a fresh process starts with zero rows and the clock at `2026-08-01T00:00:00Z`.

## Coverage audit

```
scaffold endpoints: 81  prd endpoints: 81  implemented: 81
missing (scaffold - impl): []   missing (prd - impl): []   extra (impl - scaffold): []
catalog errors: 50  implemented: 50   missing: []   extra: []
raised in code: 50   never raised: []
```

## Verification

- Lifecycle smoke suite (`/tmp/smoke2235.py`): full happy path plus ~30 negative-path error-ID/ordering assertions — PASSED.
- Cascade suite (`/tmp/smoke2235b.py`): 4-hop submittal-revision revocation (release REVOKED, lot ON_HOLD with `status_before_hold`, zone → REMEDIATION with cleared `certified_line_cents`, package `WEATHER_TIGHT_ACHIEVED → IN_INSTALLATION` and earned value back to 0), re-release un-holding the lot, escalation → `FROZEN` blocking, `ERR_DISPUTE_REF_REQUIRED` escape, field-test-failure cascade, glass re-fire cascade (risk 50.71 → 82.42 flips the flag, revokes the release, and subsequently trips `ERR_GLASS_RISK_THRESHOLD_EXCEEDED`; tier-2 expedite recovers to eff. 36 days), `ERR_BILLING_EXCEEDS_CONTRACT`, hoist buffer conflict/re-book, late-zone `ERR_ZONES_NOT_WEATHER_TIGHT`, and pagination clamping — PASSED.
- Live HTTP boot via `bash start.sh` on a free port: list/create/clock/404/405/malformed-body all return correctly shaped envelopes.

Two spec-ordering points worth flagging, both resolved in favour of the normative §2.12 step 14 list (my initial test expectations were the thing that was wrong, not the code): an unresolved `FAILED` field test reports `ERR_NO_FIELD_TEST_EVIDENCE` ahead of `ERR_OPEN_CRITICAL_DEFECT`, and `ERR_ENGINEERING_POSTURE_FROZEN` outranks both. Also note the package bubble edges are strictly per-trigger, so setting anchors while a package is still `MOCKUP_QUALIFIED` (i.e. before any release) leaves the state unchanged, exactly as the literal `IN_FABRICATION → IN_INSTALLATION` wording requires.

## Step 7: Run Tests and Iterate — 2026-09-01T13:56:00.000Z

All 8 parallel rounds now pass 119/119.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep). Iteration 1: 111/119 in all 8 rounds, 8 stable failures, no flakiness observed. Iteration 2: 119/119 in all 8 rounds.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` → `add_approved_submittal()`: `notes_count` was being splatted into the *submittal-creation* payload instead of the *review* payload, so every `decision="APPROVED_AS_NOTED"` setup died on `ERR_INVALID_REQUEST - field 'notes_count' is required`. It is now a named parameter routed to `review_submittal`, defaulting to 1 on the `APPROVED_AS_NOTED` branch per PRD §3.2 ("requires the payload's `notes_count` to be at least 1"). Fixed 3 tests (`test_04` ×2, `test_14` reopen test).

**Fixes applied to `test_suite/`** (assertion mis-translations of PRD, each made *more* faithful)
- `test_07_cross_entity_state_dependency.py` → `test_qualifying_the_mockup_changes_which_gate_refuses_the_same_payload`: asserted `ERR_MOCKUP_NOT_QUALIFIED` while its own fixture left the submittal in `UNDER_REVIEW`. PRD §2.12 #12 is normative: `ERR_SUBMITTAL_NOT_APPROVED` **outranks** `ERR_MOCKUP_NOT_QUALIFIED`. Re-sequenced so the gate flip runs in PRD order (unapproved submittal masks the mockup; approving it uncovers `ERR_MOCKUP_NOT_QUALIFIED`; the retest then qualifies the package). Both gates are still exercised.
- `test_11_state_machines.py` → `test_the_major_defect_waives_and_the_critical_one_cannot`: exact `ERR_OPEN_CRITICAL_DEFECT` relaxed to `validate_error_is_one_of([ERR_OPEN_CRITICAL_DEFECT, ERR_NO_FIELD_TEST_EVIDENCE])` (plus an explicit 422 check). **Error-precedence silence:** the setup also violates PRD §3.8's bullet "No field test of the zone may be in state `FAILED` whose linked defect item is not yet `CLOSED` or `WAIVED`" — a rule PRD states but assigns **no error id**, and which §2.12 #14 orders *ahead* of `ERR_OPEN_CRITICAL_DEFECT`. Both codes are PRD-faithful; permitted relaxation, not a weakening.
- `test_13_validations.py` → `test_the_reinspection_and_the_result_recording_refuse_an_absent_user_too`: removed the assertion that recording a field-test result without `X-User-ID` yields `ERR_MISSING_USER`. **PRD silence (partial coverage, §1c):** PRD §2.1/§2.12 #3 enumerate exactly five operations requiring `X-User-ID` — seal, review start, review decision, defect re-inspection, crew-day posting — and field-test result recording is *not* one of them; the test's own cited quote contradicts the assertion. The covered half (re-inspection refused) and the tail (result stamps `recorded_by_user_id`) were kept.

**Fixes applied to `implementation/`**
- `workspace/implementation/routes_core.py` → `start_review()` and `review_submittal()`: added the missing terminal-state guard (`state in ("APPROVED","VOIDED")` → `ERR_TERMINAL_STATE`) ahead of the invalid-state check. `resubmit()` and `reopen_review()` already had it, so the module was internally inconsistent; PRD §2.12 #10 lists `APPROVED`/`VOIDED` among the terminal values reported "on every action endpoint against an entity with terminal states", and §3.2 states "`APPROVED` is terminal: the submittal accepts no further transitions". Fixed `test_11` terminal-rows and `test_16` masked-business-rule tests. No non-terminal path changed, so the suite's `ERR_INVALID_STATE` expectations (review on `SUBMITTED`, close-notes on `SUBMITTED`, reopen on a burned-down `APPROVED_AS_NOTED`, second system decision) all still hold.

No implementation check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory with no startup seeding.

## Step 8: Finalize PRD — 2026-09-01T14:12:00.000Z

Done. `PRD_FINALIZED.md` created with two inline edits, both traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 484 lines / 94,707 bytes
- `PRD_FINALIZED.md`: 484 lines / 95,874 bytes
- **%-delta: 0.0% lines (both edits are inline within existing lines); +1.23% bytes (+1,167)**

## Changes
- **§3.2 (Delegated Design, final paragraph)** — *insert* — pins that the four submittal edges that declare a transition (start-review, review, resubmit, reopen-review) report `ERR_TERMINAL_STATE` for a submittal in `APPROVED`/`VOIDED`, with the terminal check evaluated *ahead* of the edge's own from-state check; explicitly carves out seal and note burn-down, which report `ERR_INVALID_STATE` instead — `implementation/routes_core.py:325-328, 368-371, 419-422, 450-455` (terminal-first) vs `:303-304, 474-475` (invalid-state only).
- **§3.8 (certification bullet list, failed-test bullet)** — *insert* — assigns the previously unnamed rule an error id: it shares `ERR_NO_FIELD_TEST_EVIDENCE` with the preceding two-kind evidence bullet, is evaluated immediately after it (hence ahead of `ERR_OPEN_CRITICAL_DEFECT`, matching §2.12 #14), and does not trip when a `FAILED` test has no linked defect — `implementation/routes_zones.py:212-222`.

Items from `<step_7_diff>` deliberately **not** patched:
- `test_helpers/fixtures.py` `notes_count` routing — pure fixture bug; PRD §3.2 + §2.12 #4/#6 already determine `ERR_INVALID_REQUEST` on absence (`routes_core.py:359-365`) and `ERR_VALUE_OUT_OF_RANGE` below 1.
- `test_07` gate re-sequencing — PRD §2.12 #12 already normative and `routes_glass.py:234-239` follows it exactly.
- `test_13` `X-User-ID` on field-test result recording — `routes_qc.py:305` uses the non-enforcing `user_id()` (not `require_user()`), so impl already matches PRD §2.1/§2.12 #3's closed list of five operations.

## Per-edit pre-edit search log

**Edit 1 — §3.2 terminal-state on submittal edges**
- (a) Subject: which error a submittal action endpoint reports when the submittal sits in a terminal state, and its precedence vs. `ERR_INVALID_STATE`.
- (b) Enumerated/read: grepped `ERR_TERMINAL_STATE|ERR_INVALID_STATE` across all of `implementation/`. Submittal endpoints in `routes_core.py`: `seal_submittal` (`:303`, invalid-state only, no terminal guard), `start_review` (`:325-328`), `review_submittal` (`:368-371`), `resubmit` (`:419-422`), `reopen_review` (`:450-455`, terminal → wrong-state → notes<1), `close_notes` (`:474-475`, invalid-state only). Also enumerated non-submittal terminal-check sites to make sure no global ordering claim was implied: `close_out` (`routes_core.py:151-154`), `system_decision` (`:124`, `CLOSED_OUT` package → `ERR_INVALID_STATE`), `start_production`/`receive_glass` (`routes_glass.py:99, 156`, `CLOSED` order → `ERR_INVALID_STATE`), `request_expedite` (`:142`), `advance_fabrication` (`:356`), `cancel_draw` (`:465`), `record_survey`/`confirm_pour` (`routes_zones.py:369, 395`), `void_crew_day` (`:489`), `cancel_reservation` (`:658`), `record_mockup_result` (`routes_qc.py:174`), `record_field_test_result` (`:313`), defect `submit-remediation`/`reinspect`/`waive` (`:452, 475, 512`), plus zone axes (no terminal values).
- (c) Adjustment: the first draft said terminal checks precede from-state checks generally; that would have mis-described `routes_glass.py:99/156` and `routes_core.py:124` (both return `ERR_INVALID_STATE` for a terminal parent) and `seal`/`close-notes`. Re-scoped the sentence to the four named submittal edges, added an explicit carve-out for seal and note burn-down, and made no statement about §2.12 #10's general ordering for other entities.

**Edit 2 — §3.8 failed-test bullet error id**
- (a) Subject: the rejection code and precedence position of the "no `FAILED` field test with an unresolved linked defect" certification precondition.
- (b) Enumerated/read: grepped `ERR_NO_FIELD_TEST_EVIDENCE` across `implementation/` — only `errors.py:106` (422) and `routes_zones.py:211` (two-kind evidence) / `:222` (failed-test linked defect); `certify_weather_tight` is the sole emitting endpoint. Read the full gate order in `certify_weather_tight` (`routes_zones.py:200-238`) and confirmed `:222` precedes `ERR_OPEN_CRITICAL_DEFECT` at `:225`, matching §2.12 #14's existing order. Read `routes_zones.py:215-219` (the "linked" predicate matches any defect row whose `field_test_id` equals the test id, unscoped by zone/package) and `domain.open_critical_defects` (`domain.py:372-384`, zone-scoped at this callsite). Also checked the parallel defect-creating path `routes_qc.py:340-362` to confirm each `FAILED` field test normally does get a linked defect.
- (c) Adjustment: kept PRD's existing "linked defect item" phrase verbatim rather than restating the matching rule (impl matches unscoped by zone, so a narrower phrasing would have been a new mismatch), and added the explicit "no linked defect item at all does not trip this bullet" clause because impl's empty-`linked` loop is vacuously satisfied.

## Step 9: Complete PRD — 2026-09-01T14:57:00.000Z

`PRD_COMPLETED.md` is on disk and the walk over `implementation/` is complete.

## Size

| | lines | bytes | chars |
|---|---|---|---|
| `PRD_FINALIZED.md` | 484 | 95,874 | 95,490 |
| `PRD_COMPLETED.md` | 484 | 118,288 | 117,790 |
| delta | **0** | **+22,414** | **+22,300** |

No sections, headings, paragraphs, table rows or list items were added or removed — every change is an in-paragraph insert or revision, so the line count is byte-for-byte structurally identical. 34 diff blocks.

## Counts

- **ambiguity-pins: 60**
- **mismatch-revisions: 16**

## Changes

**§2.1**
- §2.1 — insert — ambiguity — `X-Role` accepted as alias when `X-User-Role` absent; surrounding whitespace trimmed before matching — `validate.py:96-101`
- §2.1 — insert — ambiguity — the four optional-`X-User-ID` operations record null and skip the segregation comparison rather than failing — `routes_qc.py:164,306,386`, `routes_core.py:447`
- §2.1 — insert — ambiguity — "all roles" is the closed set of eight; any other role string is `ERR_UNAUTHORIZED` even on a pure read — `validate.py:102-104`

**§2.3**
- §2.3 — revise — mismatch — out-of-range/unparseable `limit`/`offset` are clamped, never rejected; no pagination error code exists — `validate.py:paginate`
- §2.3 — insert — ambiguity — ties at the same logical instant break by insertion order — `store.py:160-161`
- §2.3 — insert — ambiguity — the zone-scoped crew-day view orders `work_date` then `created_at`, the one exception to `created_at` ordering — `routes_zones.py:279-290`
- §2.3 — insert — ambiguity — nested single-parent views omit `limit`/`offset`/`total_count`/`has_more` from `meta` entirely — `common.py:15-19`
- §2.3 — insert — ambiguity — enum filters validated to `ERR_INVALID_ENUM`; free-text filters exact and unvalidated; empty value treated as absent — `validate.py:q_enum/q_str/q_int`
- §2.3 — insert — ambiguity — `risk_flag` filter matches `true/false/1/0` case-insensitively — `validate.py:260-272`

**§2.4**
- §2.4 — revise — mismatch — `version` tracks *effective* change: a write whose updates all equal stored values leaves `version`/`updated_at` untouched — `store.py:148-157`
- §2.4 — revise — mismatch — removed the false "survey re-attempt repeating measurements" no-op example; a monotonic counter in the update set always bumps — `routes_zones.py:377-386`
- §2.4 — insert — ambiguity — derived-view writes: crew-day posting leaves zone `version` alone; breakage draw/cancel always bump order `version` — `routes_zones.py:457-458`, `routes_glass.py:437,473`

**§2.6**
- §2.6 — revise — mismatch — zone-addressed endpoints and field-test record-result resolve the addressed row *before* body validation; named as the one documented exception to §2.12 — `routes_zones.py:197-198`, `routes_qc.py:308-311`
- §2.6 — insert — ambiguity — a crew day addressed under the wrong zone reports `ERR_RESOURCE_NOT_FOUND` — `routes_zones.py:485-487`

**§2.7**
- §2.7 — insert — ambiguity — `remaining_crew_hours` derives from the already-rounded `consumed_crew_hours` — `domain.py:356-357`
- §2.7 — insert — ambiguity — `straight_person_hours`/`overtime_person_hours` are exact products, never rounded; integer field list enumerated — `calc.py:145-149`

**§2.8**
- §2.8 — insert — ambiguity — both version fields are plain ints; a non-integer is `ERR_INVALID_REQUEST`, not a stale-version failure — `routes_glass.py:200,402`
- §2.8 — revise — mismatch — issuing a release does not bump package `version` unless the `MOCKUP_QUALIFIED → IN_FABRICATION` bubble fires — `routes_glass.py:289-290`
- §2.8 — insert — ambiguity — a draw always bumps order `version` by 1, so a second draw must quote a fresh read — `routes_glass.py:437`

**§2.9**
- §2.9 — revise — mismatch — recompute-trigger list corrected: submittal creation added; only *failing* field-test results; seal, start-review, close-notes and passing field tests never touch the package row — `routes_core.py:271`, `routes_qc.py:340-365`
- §2.9 — insert — ambiguity — a `CLOSED_OUT` package's earned-value block is never re-derived again — `domain.py:464-465`

**§2.12**
- §2.12 #6 — insert — ambiguity — added survey recording bounds (≥0), expedite tier {1,2}, review `notes_count` — `routes_zones.py:364-365`, `routes_glass.py:138`, `routes_core.py:360-365`
- §2.12 #7 — revise — mismatch — removed laboratory registration from `ERR_INVALID_WINDOW`; `LAB_SPECS` carries no window — `routes_qc.py:35-39`
- §2.12 #10 — revise — mismatch — coating-revision inverts the ordering: after-receipt beats both from-state and terminal — `routes_glass.py:111-114`
- §2.12 #10 — revise — mismatch — system decision, production start and receipt report `ERR_INVALID_STATE` for every inadmissible state, terminal ones included — `routes_core.py:123`, `routes_glass.py:98,155`

**§3.1**
- §3.1 — insert — ambiguity — the ignored `system_type` on package creation is still enum-validated — `routes_core.py:59`
- §3.1 — insert — ambiguity — `closeout_note` opens null on the package row — `routes_core.py:90`
- §3.1 — insert — ambiguity — a zone opens with `certification_note` null and both dimensional limits derived at creation time — `routes_zones.py:93,96`
- §3.1 — insert — ambiguity — retune-joint declares no from-state and never touches the package — `routes_zones.py:264-277`

**§3.2**
- §3.2 — insert — ambiguity — blank/absent `seal_license_no` → `ERR_SEAL_INVALID`; wrong JSON type → `ERR_INVALID_REQUEST`, reported ahead of the 404 — `routes_core.py:299-308`
- §3.2 — revise — mismatch — `decision` vocabulary is exactly three values; `ESCALATED` in the payload is `ERR_INVALID_ENUM` — `routes_core.py:349-356`
- §3.2 — insert — ambiguity — `notes_count` mandatory only on `APPROVED_AS_NOTED`, `ERR_INVALID_REQUEST` when absent and `ERR_VALUE_OUT_OF_RANGE` below 1, both before the 404 — `routes_core.py:359-365`
- §3.2 — insert — ambiguity — resubmit persists `dispute_resolution_ref` when supplied and retains `review_decision`/`escalation_ref` — `routes_core.py:427-437`
- §3.2 — insert — ambiguity — reopen requires `reopen_reason`, refuses `open_notes_count` 0 with `ERR_INVALID_STATE`, and treats `X-User-ID` as optional — `routes_core.py:447-461`

**§3.3**
- §3.3 — insert — ambiguity — laboratory is the one entity with no dedicated 404 code (`ERR_RESOURCE_NOT_FOUND`); `name` filter is exact — `routes_qc.py:61,68`
- §3.3 — insert — ambiguity — retest pointer resolves to `ERR_TEST_NOT_FOUND` ahead of the lab; surcharge keyed on the pointer alone, never `attempt_no`; no consistency checks — `routes_qc.py:96-98`, `calc.py:260-271`
- §3.3 — insert — ambiguity — all three mockup measurements mandatory whatever the outcome, and the invoice is re-priced to identical values — `routes_qc.py:166-203`
- §3.3 — insert — ambiguity — auto mockup defect field set enumerated with its server-written description — `routes_qc.py:213-232`

**§3.4**
- §3.4 — insert — ambiguity — `expedite_authorized` is a commercial annotation and never gates — `routes_glass.py:134-147`
- §3.4 — insert — ambiguity — expedite declares no from-state; only `CLOSED` refuses it, with `ERR_TERMINAL_STATE`; it never revokes — `routes_glass.py:141-146`
- §3.4 — insert — ambiguity — receipt refuses every other state with `ERR_INVALID_STATE` — `routes_glass.py:155-156`
- §3.4 — revise — mismatch — rescoring is read-only with respect to *state* only: it writes the whole risk block and bumps `version` when any of the five values moves — `routes_glass.py:169-175`
- §3.4 — insert — ambiguity — order `CLOSED` is evaluated at exactly one moment, lot shipment, and nowhere else — `routes_glass.py:389-390`

**§3.5**
- §3.5 — insert — ambiguity — `zone_ids` elements must be strings (checked before every other field); an empty array is accepted and yields `lot_count` 0 — `routes_glass.py:208-214`
- §3.5 — revise — mismatch — the balance check uses the fixed two-lites-per-panel constant, not the release's `lites_per_panel` — `routes_glass.py:241`
- §3.5 — insert — ambiguity — `system_type_at_release` is a verbatim copy and may be `UNDECIDED` — `routes_glass.py:257`
- §3.5 — insert — ambiguity — the un-hold sweep is keyed on covered zones plus `SUBMITTAL_REVISION` alone, runs after lot minting, and never inflates `lot_count` — `domain.py:unhold_lots_for_release`, `routes_glass.py:285-287`
- §3.5 — insert — ambiguity — advance-fabrication code map: every precondition failure is `ERR_INVALID_STATE`; `ERR_TERMINAL_STATE` only for already-`SHIPPED`, checked first — `routes_glass.py:356-372`

**§3.6**
- §3.6 — insert — ambiguity — nothing limits a zone to one survey; the anchor gate is satisfied by *any* `POURED` survey — `routes_zones.py:128-134`
- §3.6 — insert — ambiguity — survey measurements ≥0, `surveyed_by_user_id` may be null, `ACCEPTED` → `ERR_INVALID_STATE` / `POURED` → `ERR_TERMINAL_STATE`, `poured_at` normalised to UTC 3-digit — `routes_zones.py:364-401`
- §3.6 — insert — ambiguity — buffer is whole minutes defaulting to 45; rig `status` is never inspected or changed by anything — `routes_zones.py:517-523,600-610`
- §3.6 — insert — ambiguity — reservation check order window → zone → rig, with no zone/rig cross-check — `routes_zones.py:592-598`
- §3.6 — insert — ambiguity — hang-panels resolves the reservation immediately after the zone, before all four conditions — `routes_zones.py:148-152`

**§3.7**
- §3.7 — insert — ambiguity — the provisional rate tests for `UNITIZED` alone, so an undecided package falls to 6 panels/day and yields 0 cents — `calc.py:125-142`
- §3.7 — insert — ambiguity — duplicate check compares literal `YYYY-MM-DD` strings, `VOIDED` never blocks, no zone-status gate, posting writes nothing on the zone, `day_index` re-packed across all siblings — `routes_zones.py:423-458`
- §3.7 — revise — mismatch — voiding bumps the zone's `version` unconditionally, the one write that touches a zone's `version` without changing a stored zone field — `routes_zones.py:504-505`

**§3.8**
- §3.8 — insert — ambiguity — `attempt_no` is a free label with no uniqueness enforced; `scheduled_for` accepts any instant with no window or ordering validation — `routes_qc.py:240-274`
- §3.8 — insert — ambiguity — the zone `PANELS_HUNG` check runs after the terminal/from-state checks; other kinds' measurements are ignored and their fields stay null forever — `routes_qc.py:310-319`
- §3.8 — insert — ambiguity — a null `deflection_limit_mm` at recording time fails the test rather than raising — `routes_qc.py:332-333`
- §3.8 — insert — ambiguity — auto field-test defect carries `mockup_test_id` null, a server-written `Field test failed: {reason}` description, and a possibly-null raiser — `routes_qc.py:342-359`
- §3.8 — insert — ambiguity — manual defect reference resolution order (package → zone-in-package → field test → mockup test) with no origin/pointer/ownership cross-checks — `routes_qc.py:388-398`
- §3.8 — insert — ambiguity — re-inspection demands `X-User-ID`; the conflict check applies only when a raiser is recorded and is evaluated last — `routes_qc.py:471-480`
- §3.8 — revise — mismatch — both re-inspect branches run the identical package recomputation; there is no PASS-only recount — `routes_qc.py:501-503`
- §3.8 — insert — ambiguity — waive admits `OPEN` alone, so a critical item in `REMEDIATION_SUBMITTED` reports `ERR_INVALID_STATE` ahead of `ERR_WAIVER_NOT_PERMITTED` — `routes_qc.py:512-517`
- §3.8 — revise — mismatch — the evidence test is not attempt-sensitive; any currently-`PASSED` test of each kind satisfies it whatever its `attempt_no` — `routes_zones.py:208-211`
- §3.8 — revise — mismatch — `weather_status` is the first condition checked and an already-`WEATHER_TIGHT` zone reports `ERR_INVALID_STATE`, not `ERR_TERMINAL_STATE`, ahead of the sequence check — `routes_zones.py:200-203`
- §3.8 — insert — ambiguity — failed-test linkage is read from the defect side by `field_test_id` across the whole collection; every linked item must be resolved — `routes_zones.py:212-222`
- §3.8 — insert — ambiguity — the critical-defect scan is strictly zone-scoped, so null-`zone_id` package defects bite only through the posture bullet — `domain.py:372-384`
- §3.8 — insert — ambiguity — a null `thermal_movement_allowance_mm` is refused with `ERR_THERMAL_MOVEMENT_EXCEEDED`; equality passes — `routes_zones.py:227-229`
- §3.8 — insert — ambiguity — the billing comparison is strict `>`, so a line landing exactly on `contract_value_cents` is accepted — `routes_zones.py:237-238`
- §3.8 — insert — ambiguity — `certification_note` written only when supplied; the `WEATHER_TIGHT_ACHIEVED` bubble fires only from `IN_INSTALLATION` — `routes_zones.py:247-259`

**§3.9**
- §3.9 — insert — ambiguity — EV zone order includes an insertion tie-break, compares timestamps as literal ISO strings, and sorts a null `weather_tight_at` first — `domain.py:412-421`
- §3.9 — insert — ambiguity — `certified_subtotal_cents` exists only in the computed read, which is not state-gated and keeps re-deriving after `CLOSED_OUT` — `routes_core.py:195-209`, `domain.py:424`
- §3.9 — insert — ambiguity — a package with zero zones is refused close-out with `ERR_ZONES_NOT_WEATHER_TIGHT` — `routes_core.py:159-161`
- §3.9 — insert — ambiguity — full close-out evaluation order given, with the package-scoped (not zone-scoped) critical-defect scan first — `routes_core.py:151-186`
- §3.9 — insert — ambiguity — the freeze is by omission, not a flag: posture fields stay live after `CLOSED_OUT` while the money never moves again — `domain.py:464-465`, `routes_core.py:188-191`

Also confirmed as already-pinned and left untouched: the §5 error catalogue (exact match with `errors.py`, all 51 codes and statuses), the entire §4 endpoint/role table (exact match with the four blueprints), §2.2's envelope shape (`envelope.py`), the §2.10 ledger identities, and every formula constant in `calc.py`.
