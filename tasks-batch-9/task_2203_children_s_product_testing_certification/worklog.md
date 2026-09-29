# Worklog — task_2203_children_s_product_testing_certification

## Step 1: Create task directory — 2026-08-31T18:05:10.395Z

Created `tasks/task_2203_children_s_product_testing_certification/` and `tasks/task_2203_children_s_product_testing_certification/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T01:57:49.000Z

RESUME NOTE (orchestrator): the first two scaffold-generator subagents were killed by the stream watchdog ("no progress for 600s"), both dying inside their first reasoning block right after beginning to read SKILL.md. The third attempt succeeded after being given an explicit anti-stall protocol: read SKILL.md in ~170-line slices via Read offset/limit, externalize the plan to a scratch `.scaffold_plan.md` between slices, never read `examples/*.yaml` (25–66KB each, explicitly non-normative), and build each output file incrementally across many Write/Edit calls rather than one giant Write. Subagent summary follows verbatim.

All three scaffold files are complete and the linter reports a clean verdict.

## Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2203_children_s_product_testing_certification/`
- `SCAFFOLD.yaml` (3,525 lines) — §1.0–§1.7 plus preamble; no design keys present (top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (3,075 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2,553 lines) — single key `scaffold_corner_design`
- `.scaffold_plan.md` deleted.

## Counts
| Dimension | Count |
|---|---|
| Entities | 15 |
| Endpoints | 66 |
| State machines | 9 (Product, TestOrder, ChildrensProductCertificate, NoncomplianceCase, SamplingPlan, ProductionBatch, LabAccreditation, ComponentPartCertificate, ComponentPart) |
| Concurrency rules (OCC) | 2 |
| Calculations | 18 |
| Validations | 43 (priorities 1–43) |
| Errors | 56 |
| Roles | 6 (4 opaque, 2 entity-backed) |
| §1.8 rules / instances | 9 / 22 (2,3,2,2,3,3,2,2,3) |
| §1.9 sections / instances | 9 / 89 (14 entities, 15 state_machines, 16 calculations, 14 validations, 9 endpoints, 7 errors, 6 rbac, 6 layers, 2 consistency_model); 78 carry `test_recipe`, 11 carry `excluded_because` |

## Linter
`scaffold_lint.py` → **clean**: 66 endpoints, 15 entities, 22 §1.8 instances, 78 §1.9 instances, 492 calls scanned; all calls conform to §1.5 and all FKs have reverse-reachability. All three files `yaml.safe_load` cleanly; tails verified non-truncated.

## Coverage audit
- All 56 error ids, all 18 calculations, all 9 state machines and all 6 roles are referenced by at least one design instance.
- Instance names unique across both design files (0 duplicates); every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name (11/11).
- No forbidden concurrency vocabulary remains (one "simultaneously" was found and reworded).

## Scaffold defects found and fixed while authoring §1.9
- **Validation 34 (`ERR_EVIDENCE_PATH_MISMATCH`) contradicted its own error condition** — the check banned every non-retest order on the COMPONENT_RELIANCE path, which made the reliance-discount branch of `test_order_invoice_total_cents` unreachable and invalidated the §1.8 mode-c instance. Rewritten to ban only orders for rules *already fully covered* by RELIED_UPON component certificates, and `applies_to` extended to the reliance-documentation endpoint.
- **Validation 6 made 3 error codes unreachable** — `ERR_MAPPING_NOT_FOUND`, `ERR_ACCREDITATION_NOT_FOUND` and `ERR_PART_CERTIFICATE_NOT_FOUND` were folded into their parents' codes. Rewritten as an explicit 15-way one-code-per-entity map covering both path parameters and body foreign keys (`applies_to` updated accordingly).
- Earlier in the run: added the two `MaterialChangeEvent` GETs (FK reverse-reachability), added `POST /compliance/category-rule-mappings/{mapping_id}/retire` (made enum `RETIRED` reachable), added validation 43 + `ERR_ACCREDITATION_STATE_INVALID`, extended validation 12 to cover batch release, merged validation 31 with the coverage-month window, and retriggered `ComponentPart PENDING→VALID` off a certificate entering `RELIED_UPON`.

Orchestrator verification: all three files `yaml.safe_load` cleanly; `SCAFFOLD.yaml` confirmed free of both `scaffold_difficulty_design` and `scaffold_corner_design` keys; counts independently confirmed (entities 15, endpoints 66, state_machines 9, calculations 18, validations 43, errors 56, roles 6); tails of all three files non-truncated.

## Step 3: Copy shared files — 2026-09-01T01:57:49.000Z

Copied `INSTRUCTION.md` (53 lines) from the project root to `tasks/task_2203_children_s_product_testing_certification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T02:17:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2203_children_s_product_testing_certification/workspace/PRD.md` — 507 lines, 122,771 characters. Ends cleanly at the last row of the §5 error table. Scratch file `.prd_plan.md` deleted (verified absent).

**Section outline**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Audit Stamps and the Logical Clock · 2.5 Reference Resolution and Nested Path Validation · 2.6 Stale-Snapshot Protection · 2.7 Arithmetic, Rounding and Evaluation Order · 2.8 Conservation Ledgers and Compensating Actions · 2.9 Cascade Discipline and Version Propagation · 2.10 Laboratory Integrity and Undue-Influence Prevention · 2.11 The Order in Which Refusals Are Decided (explicit 1–43 list)
- §3 Business Logic: 3.1 Regulatory Reference Library · 3.2 Party Register · 3.3 Product Registration, BOM and Rule Identification · 3.4 The Two Evidence Paths · 3.5 Sampling Plans and Periodic Verification · 3.6 Booking and Executing Third-Party Testing · 3.7 The Children's Product Certificate · 3.8 Production Batches, Tracking Labels and Distribution Control · 3.9 Noncompliance Response · 3.10 Material-Change Log and Resample Cascade
- §4 API Endpoints (4-column table, 66 rows)
- §5 Error Codes (2-column table, 56 rows)

**Coverage audit (machine-verified)**
| Item | Covered / Total |
|---|---|
| Endpoints | 66 / 66 (all 61 unique paths present; §4 table has exactly 66 rows, 4 columns) |
| Error IDs | 56 / 56 (§5 has exactly 56 rows, 2 columns) |
| Validations | 43 / 43 (§2.11 numbered 1–43, each with check, error id, HTTP status, exhaustive `applies_to`) |
| Calculations | 18 / 18 (each formula given in natural language with constants and rounding) |
| State machines | 9 / 9; all 55 transitions covered with from/to, preconditions and side effects |
| Roles | 6 / 6 |
| Concurrency rules | 2 / 2 (§2.6) |
| Named cascades | 4 / 4 |

**Hard Contracts**
- **Contract 1 (Field-Name Coverage): PASS.** All 151 identifiers (entity field names + endpoint body/query inputs + path params) appear verbatim in backticks. Zero missing. The 15 path-parameter names were initially only present inside backticked full paths; I added an explicit enumeration in §2.5 so each appears as a standalone backticked token.
- **Contract 2 (Rule Coverage): PASS.** Validation priority ordering enumerated 1–43; both OCC rules stated with their write operation, `expected_product_version` / `expected_case_version`, `ERR_STALE_PRODUCT_VERSION` / `ERR_STALE_CASE_VERSION` and 412; all four cross-entity cascades given hop-by-hop; every `applies_to` scope enumerated exhaustively rather than summarised; field-level constraints, enums and defaults stated; sibling branches written at equal density (RELY/REJECT, BATCH_SCOPED/LOT_TRACEBACK, INITIAL/PERIODIC sizing, PASS/FAIL, triggers_resample true/false, cycle vs loop-termination retest edge).
- **Contract 3 (§3 Path Purity): PASS.** Scan of every backticked token in §3 found zero tokens beginning with `/`, zero bare HTTP methods and zero method+path combinations. Endpoints in §3 are referenced only by role + action verb, state-transition framing or capability description. The HTTP contract appears only in §4.

**Scaffold defects / ambiguities resolved (8)**
1. `ERR_UNAUTHENTICATED` scope: catalog exempts the clock endpoint, but validation priority 1 is `applies_to: all` and the clock endpoint has a `roles:` list. Resolved as headers required on every endpoint.
2. ComponentPart `PENDING → VALID` circularity: the transition precondition requires `reliance_status == VALID` while the state machine's reliance-branch side effect sets parts to `VALID`, making `RELIED_UPON` unreachable under the narrow reading. Resolved: reliance branch promotes every `PENDING` part; later-added parts reach `VALID` once every applicable required rule holds a relied-upon certificate.
3. REJECT branch and `reliance_documentation_ref`: state machine sets it, endpoint says it stays null. Resolved in favour of the state machine.
4. Laboratory billing timing: billed both at order creation and on `SCHEDULED → IN_TESTING`. The `laboratory_fee_ledger` invariant counts `SCHEDULED` orders, forcing billing at creation. Resolved: bill exactly once, at creation.
5. Cancellation credit: `SCHEDULED → CANCELLED` note says no credit "because nothing was billed", but the endpoint credits unconditionally and the ledger invariant requires it. Resolved: credit on both cancellation edges.
6. `RESAMPLE_DUE → LAPSED` inclusivity: transition precondition is strictly after the grace deadline; endpoint says "at or after". Resolved: strictly after.
7. `ERR_LAB_METHOD_NOT_ACCREDITED` coverage anchor: catalog anchors on the order's `window_start`; validation 21 and `lab_test_line_fee_cents` anchor on the logical clock. Resolved: logical clock (2 of 3 sources).
8. **New:** the `OPEN → STOP_DISTRIBUTION_ISSUED` precondition "product has at least one batch in HELD or RELEASED" has no dedicated error id anywhere in the catalog. Resolved by mapping it to `ERR_CASE_STATE_INVALID` (409), the nearest gate on that operation; flagging it since a downstream test generator may expect a distinct code.

Orchestrator verification: `workspace/PRD.md` is 507 lines / 122,771 chars, ends at the final `ERR_SAMPLING_FLOOR_NOT_MET` error-table row (natural boundary, non-truncated); §5 confirmed to hold exactly 56 `ERR_*` rows; §4 confirmed to hold 66 endpoint rows plus header and separator; scratch file confirmed absent. The anti-stall protocol (chunked reads + incremental section-by-section writes) was applied again and no watchdog kill occurred.

## Step 5 (partial, pre-crash): Generate unit tests — RESUME AUDIT 2026-09-01T03:45:00.000Z

Orchestrator resume audit of the crashed run's Step 5 output. `test_helpers/` (9 files, 2,550 lines) and `test_suite/` (13 files incl. conftest, 169 test functions) exist and all compile under `py_compile`. Design-tag coverage measured against both design indices:

| Queue | Instances (non-excluded) | Translated | Missing |
|---|---|---|---|
| Difficulty (§1.8) | 22 | 21 | 1 |
| Corner (§1.9) | 78 | 40 | 38 |

Corner sections fully translated: `entities` (14/14 → test_10, 37 tests), `state_machines` (12/12 → test_11, 33 tests), `calculations` (14/14 → test_12, 39 tests).
Corner sections with **no test file at all**: `validations` (13), `endpoints` (9), `errors` (5), `rbac` (6), `cross_cutting_complexity_layers` (3), `consistency_model` (2).
Missing difficulty instance: `priority_conflict_business_safety_reliance_agreement_outranks_business_referential_reliance_not_allowed`.
Zero bad tags (every `Design:` tag resolves to a real instance); no dual-tagged tests. Scratch file `.test_plan.md` still present (crash residue).

Verdict: Step 5 INCOMPLETE — resumed below.

## Step 6: Generate implementation — RESUME AUDIT 2026-09-01T03:45:00.000Z

Orchestrator resume audit of the crashed run's Step 6 output (no pre-crash worklog entry was written). `workspace/implementation/` contains 21 Python modules (app.py, auth.py, db.py, refs.py, clock.py, errors.py, response.py, validation.py, paging.py, services/{calc,engine,gates}.py, routes/{products,certificates,batches,orders,labs,cases,plans,partcerts,reference,events,clock}.py), `requirements.txt` and `start.sh`.

Verification performed:
- All modules compile under `py_compile`.
- `bash start.sh` with `PORT=18234` boots a Flask server in the foreground, binds `0.0.0.0`, and serves requests (verified with a live curl).
- Route-decorator extraction yields **exactly 66 method+path pairs**, an exact set-match against the 66 rows of PRD §4 (0 PRD endpoints unimplemented, 0 implementation endpoints absent from the PRD). This matches the scaffold's 66 endpoints over 61 unique paths.
- Storage is in-memory (`db.py` dicts); no SQLite file, no on-disk persistence.

Verdict: Step 6 COMPLETE — not regenerated.

## Step 5 (resumed to completion): Generate unit tests — 2026-09-01T04:37:00.000Z

Step 5 is complete. All six Corner-queue files exist, the whole suite compiles and collects, and every non-excluded design instance is covered except the one that failed the PRD filter.

## Files created (this session)

| File | Lines | Tests | Section → instances |
|---|---|---|---|
| `test_suite/test_16_rbac.py` | 951 | 25 | `rbac` — all 6 |
| `test_suite/test_17_layers.py` | 469 | 14 | `cross_cutting_complexity_layers` — all 3 non-excluded |
| `test_suite/test_18_consistency_model.py` | 295 | 8 | `consistency_model` — both 2 |

Created earlier in the resumed work: `test_13_validations.py` (1188 / 34), `test_14_endpoints.py` (1220 / 30), `test_15_errors.py` (653 / 18).

## Files edited
- `test_suite/test_16_rbac.py` — finished the file that was mid-write: added `TestFourOpaqueRolesPartitionWrites` (5 tests), `TestLaboratoryIdentityIsScopedToItsOwnOrders` (4), `TestSupplierIdentityIsScopedToItsOwnParts` (3), `TestSegregationOfDutiesComparesUserIds` (4), `TestUnauthenticatedRequestsAreRefusedFirst` (4), plus imports for the ALT identities.
- Bug fixed while cross-checking field names: one assertion used `result_outcome`; PRD 3.6 and `SCAFFOLD.yaml` line 618 name the field `result`. Corrected in `test_16_rbac.py`.
- `test_helpers/` — **not extended**; no new fixtures/factories were needed. `test_05_refusal_priority_pairs.py` — **untouched** (see skip below). `.test_plan_resume.md` deleted.

## Per-section translation table (whole suite)

| Section | Non-excluded instances | Tests | Skipped |
|---|---|---|---|
| entities | 14 | 37 | 0 |
| state_machines | 12 | 33 | 0 |
| calculations | 14 | 39 | 0 |
| validations | 13 | 34 | 0 |
| endpoints | 9 | 30 | 0 |
| errors | 5 | 18 | 0 |
| rbac | 6 | 25 | 0 |
| cross_cutting_complexity_layers | 3 | 14 | 0 |
| consistency_model | 2 | 8 | 0 |
| Difficulty (22 rules/instances) | 22 | 60 | 1 |

## Skipped instance (1 of 320 total)

**`priority_conflict_business_safety_reliance_agreement_outranks_business_referential_reliance_not_allowed`** (Difficulty / `priority_pair_validation_conflict`) — **filter 1b** (PRD sentence does not uniquely determine the asserted outcome; the recipe is also unreachable). It needs a `COMPONENT_RELIANCE` product whose only required rule has `component_reliance_allowed: false`, but PRD 3.4 makes that combination unreachable — `RELY` requires "the cited rule's `component_reliance_allowed` is true, or the request is refused with `ERR_COMPONENT_RELIANCE_NOT_ALLOWED`", and rank 22 (`ERR_RELIANCE_AGREEMENT_MISSING`) vs the reliance-allowed guard are both listed under §2.11 without a pair ordering that the PRD states for this specific pair; the recipe additionally asserts the part stays `PENDING`, which contradicts the same paragraph. No PRD sentence resolves the two 422s against each other, so the instance is reported rather than weakened.

## Design-recipe defects worked around (asserted PRD behaviour instead)
- **Supersession pointer unreachable** (`corner_layers_..._guards_the_supersession_pointer`): the recipe wants the retry's `supersedes_certificate_id` to equal the first draft, but PRD 3.7 sets it from the *currently issued* certificate and issuing moves the product to `CERTIFIED` (blocking a second draft). Asserted `is None` with the PRD sentence quoted.
- **Design contradicts PRD on `certificates_issued_count`**: the layers recipe claims it is "unchanged by a later REJECTED reliance decision", but PRD 3.4 says `REJECT` decrements it by 1. The test asserts the PRD (filing +1, `RELY` unchanged, `REJECT` −1).
- **Lab-scope "empty page" read**: the rbac recipe expects identity-filtered reads; the PRD never states read scoping, so that test asserts only HTTP 200 (PRD §4 authorises `LaboratoryUser` for both order reads).
- **Guard-rank hazard avoided**: rank 16 (`ERR_STALE_PRODUCT_VERSION`) is not listed under rank 9's "applies to" set for *drafting*, so the two-guards test drafts against a clean `EVIDENCE_COMPLETE` product rather than the `REMEDIATION` product of the case env, avoiding an ambiguous 409/412 race.

## Self-check output (verbatim)
```
$ python3 -m py_compile test_helpers/*.py test_suite/*.py
COMPILE_ALL_OK

$ python3 -m pytest test_suite --collect-only -q 2>&1 | tail -20
... 298 tests collected in 1.06s

$ python3 /tmp/tagaudit.py
test functions: 298
distinct tags: 99
untagged: []
multi-tagged: []
bad: []
entities: instances(non-excluded)=14 tests=37 uncovered=[]
state_machines: instances(non-excluded)=12 tests=33 uncovered=[]
calculations: instances(non-excluded)=14 tests=39 uncovered=[]
validations: instances(non-excluded)=13 tests=34 uncovered=[]
endpoints: instances(non-excluded)=9 tests=30 uncovered=[]
errors: instances(non-excluded)=5 tests=18 uncovered=[]
rbac: instances(non-excluded)=6 tests=25 uncovered=[]
cross_cutting_complexity_layers: instances(non-excluded)=3 tests=14 uncovered=[]
consistency_model: instances(non-excluded)=2 tests=8 uncovered=[]

difficulty instances: 22 excluded: 0
UNCOVERED difficulty: priority_pair_validation_conflict priority_conflict_business_safety_reliance_agreement_outranks_business_referential_reliance_not_allowed
```
`grep -rn "pytest.mark" test_suite/` returns nothing — no skip/xfail anywhere.

## Suite totals
19 files in `test_suite/` (18 test modules + `conftest.py`), 11,245 lines, **298 test functions**, 99 distinct `Design:` tags, every tag resolving to a real instance name, every test tagged exactly once. Tests were collected only, never executed, per instructions.

Orchestrator verification: 19 files in `test_suite/`; `pytest --collect-only -q` reports **298 tests collected** with no collection errors; `grep -rn "pytest.mark" test_suite/` returns nothing; `.test_plan_resume.md` confirmed absent.

## Step 7: Run tests and iterate — 2026-09-01T05:15:00.000Z

Done. All 298 tests pass in all 8 parallel rounds.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (baseline + 2 fix rounds).

**Final sweep result:** 298/298 passed in every one of the 8 rounds (`failed 0, errors 0` each). Zero flakiness — every round was bit-identical in outcome across all three sweeps, so no timing-sensitive bug was hiding behind a lucky round.

**Baseline:** 250/298 (48 deterministic failures, identical in all 8 rounds).

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and survived the unique-derivability check; all 48 were either an implementation defect or a test/env defect.

### Fixes applied to `implementation/`

1. **`workspace/implementation/clock.py`** — added `iso_instant(dt)` / `now_iso_instant()`: renders a domain instant at second precision (`...T00:00:00Z`), emitting `.mmm` only when the instant actually carries microseconds. *Why:* PRD §2.4 pins the "three fractional digits" format on `created_at`/`updated_at` only (and §2.2 on `api_request_timestamp`), and states the logical clock "reads **exactly** `2026-08-01T00:00:00Z`". The old code rendered every datetime with forced `.000Z`, which both reformatted client-supplied instants the PRD never authorises the server to rewrite, and contradicted the clock's stated exact reading. This single fix cleared **41 of the 48** failures.
2. **`workspace/implementation/db.py`** — added `AUDIT_STAMP_FIELDS = ("created_at", "updated_at")`; `serialize()` now renders those two via `iso_millis` (PRD §2.4) and every other datetime column (`window_start/end`, `valid_from/through`, `coverage_from/through`, `effective_from`, `produced_on`, `activated_at`, `last_verified_at`, `periodic_due_at`, `reported_at`, `issued_at`, `released_at`, `last_material_change_at`, `occurred_at`, `influence_attestation_valid_through`) via `iso_instant`.
3. **`workspace/implementation/routes/clock.py`** — `set_current_utc` reports `current_utc` via `now_iso_instant()`, so "the response reports the new setting" echoes the instant as set.
4. **`workspace/implementation/routes/plans.py` `activate_plan`** — moved the plan-state check (§2.11 rank 11) **before** the owning product's `certification_state` precondition. *Why:* §2.11 rank 9 explicitly scopes the product-certification-state check to "submission for certification, archival, test order booking, and certificate issuance" — plan activation is not in that set, while rank 11 explicitly is. The §3.5 product-state precondition is retained, just decided after rank 11.

No endpoint, response field, side effect or capability was added; the 66-endpoint surface is unchanged. Storage remains in-memory dicts with nothing seeded (verified).

### Fixes applied to `test_suite/`

1. **`test_01_dual_variant_calculations.py` `_two_case_distribution_env`** (2 tests: `test_batch_scoped_and_lot_traceback_scopes_diverge_on_identical_batches`, `test_stop_distribution_leaves_batches_already_stopped_where_they_are`) — removed the two `fx.release_batch` calls. *Why:* releasing both batches meant hop four of the failed-test cascade moved them `RELEASED → STOP_DISTRIBUTION` at the first failing report, after which PRD §3.9 ("A case whose product has no production batch in `HELD` or `RELEASED` has nothing to stop … refused with `ERR_CASE_STATE_INVALID`") correctly refused both stop-distribution instructions. With the batches left `HELD`, both instructions are reachable and the asserted `scope_units` figures (300 / 800) and the final ledger split are unchanged.
2. **`test_10_entities.py` `test_the_required_rule_set_stays_empty_until_scoping_derives_it`** — the empty-set assertion now reads the **registration response** rather than a re-read taken after the bill of materials was built. *Why:* the quoted sentence is "**At registration** … `required_rule_ids` is the empty array", while §3.3 separately requires re-derivation "on every component part addition while the product's `certification_state` is still `DRAFT` or `SCOPED`".
3. **`test_10_entities.py` `_clock_shifted_order_env` + `test_the_activation_instant_survives_a_later_clock_move`** — the helper now snapshots the plan (`plan_before_clock_move`) immediately before moving the clock, and the test compares `version`/`updated_at` against that snapshot. *Why:* `env["plan"]` was captured at activation, before the order booking committed units against the plan (§3.6), so it was a stale snapshot; the test's actual claim — the clock move mutates no row — is now isolated exactly, and strengthened with an `updated_at` check.
4. **`test_11_state_machines.py` `test_submission_scopes_and_forks_in_a_single_request`** — `before` is now read fresh instead of using the registration response. *Why:* §3.3 "Adding a part increments the owning product's `version` by 1" had already advanced the row, so `before["version"] + 2` was measured from the wrong baseline.
5. **`test_11_state_machines.py` `test_a_repeated_issue_and_furnish_neither_restamp_nor_advance`** — the replayed-issuance expectation changed to `ERR_PRODUCT_STATE_INVALID`. *Why:* §2.11 states verbatim "When issuing a certificate, **product state comes first**, then the certificate's own axis state"; the first issuance carried the product to `CERTIFIED`, so rank 9 pre-empts rank 12. The repeated-furnish half of the test still asserts `ERR_CERTIFICATE_STATE_INVALID`.
6. **`test_13_validations.py` `test_an_accessible_metal_part_repairs_both_empty_sets_at_once`** — expected `certification_state` changed `SCOPED` → `FULL_TEST_PROGRAM`. *Why:* §3.4 forks the product automatically inside the same request ("Both moves are automatic — no separate operator action drives them"), so `SCOPED` is never observable; the rest of the suite already asserts this.
7. **`test_13_validations.py` `test_the_success_cannot_be_replayed`** — expected error changed to `ERR_PRODUCT_STATE_INVALID`, docstring re-cited to the §2.11 precedence sentence. Same reasoning as (5).
8. **`test_14_endpoints.py` `test_every_row_creating_post_answers_201_and_its_read_answers_200`** — reordered so the product is read back **before** its component part is created, with the part's 201/200 pair checked afterwards. *Why:* the part addition legitimately bumps the product's `version` to 2 and refreshes its `updated_at` (§3.3), which broke the loop's `version == 1` and `updated_at` equality assertions. No assertion was weakened.

### Fixes applied to `test_helpers/`

None — no fixture, factory, header builder or assertion helper turned out to be at fault. (Note for the record: the tests' timestamp model, encoded in `test_helpers/constants.py::STARTUP_CLOCK` and the second-precision instants throughout `test_helpers/factories.py`, is internally consistent and PRD-faithful; `test_helpers/assertions.py` deliberately uses the loose `is_iso8601_timestamp` for `created_at`/`updated_at`, which is what let the implementation's millisecond audit stamps stay correct.)

Orchestrator note: the subagent's final-sweep `results.*.json` files were not left on disk, so the orchestrator re-ran the 8-round parallel sweep independently to regenerate them and to verify the green claim first-hand. Result recorded in the Step 7 verification entry below.

## Step 8: Finalize PRD — 2026-09-01T05:24:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2203_children_s_product_testing_certification/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 507 lines / 122,771 chars
- PRD_FINALIZED.md: 509 lines / 124,996 chars
- Delta: +2 lines (+0.39%), +2,225 chars (+1.81%). 3 edits, all inline; no new sections.

## Changes
- **§2.4 (new paragraph after the audit-stamp paragraph, line 88)** — *insert* — pins the second timestamp family: the three-fractional-digit form is exclusive to `created_at`/`updated_at` (plus §2.2's `api_request_timestamp`); every other datetime-valued field (enumerated: `effective_from`, `influence_attestation_valid_through`, `valid_from`/`valid_through`, `last_material_change_at`, `coverage_from`/`coverage_through`, `activated_at`/`last_verified_at`/`periodic_due_at`, `window_start`/`window_end`/`reported_at`, `issued_at`, `produced_on`/`released_at`, `occurred_at`) renders at whole-second precision with trailing `Z`, gaining a three-digit fraction only when the instant carries a non-zero sub-second component, truncated toward zero to milliseconds; null renders as JSON null; client-supplied instants are echoed at the precision they carried and never re-stamped — `implementation/clock.py:34-57`, `implementation/db.py:65-137`.
- **§2.4 (clock paragraph, line 90)** — *revise* — `current_utc` is reported under the same whole-second instant rule, so the startup clock reads back exactly `2026-08-01T00:00:00Z` — `implementation/routes/clock.py:19`.
- **§3.5 (activation paragraph, line 277)** — *insert* — pins the activation-only refusal order: archival guard → plan's own `plan_state` (rank 11) → product's `certification_state` → sampling floor, with an explicit note that the four rank-9 operations are unaffected — `implementation/routes/plans.py:100-110`.

**No edit made** for the Step 5 gap (rank 22 vs `ERR_COMPONENT_RELIANCE_NOT_ALLOWED`): `implementation/routes/partcerts.py:127-135` evaluates agreement (22) → rule applicability (32) → reliance allowed (33) → evidence path (34), which is exactly what §2.11's existing rank numbers already determine. Also no edits for test-suite items 1–8: each traces to a fixture/ordering bug against prose PRD.md already pins verbatim (§3.9 stop-distribution precondition, §3.3 "At registration … empty array" + re-derivation on part addition + `version` increment, §2.11 line 201 "product state comes first", §3.4 line 251 automatic same-request fork).

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp families.**
(a) Subject: rendering format of every datetime value any response carries.
(b) Paths enumerated: `clock.py` `iso_millis`/`iso_instant`/`now_iso_millis`/`now_iso_instant`; `db.py` `DATETIME_FIELDS` (all 15 tables) + `AUDIT_STAMP_FIELDS` + `serialize`/`serialize_many`; `paging.build` (only list path, routes through `serialize_many`); `response._meta` (`api_request_timestamp` → `iso_millis`); `routes/clock.py` (`current_utc` → `iso_instant`); grep for all `iso_*` callers (only those three modules); grep for every `"*_at"/"*_from"/"*_through"/"*_on"` row key written anywhere in `routes/`+`services/` (all present in `DATETIME_FIELDS`; `attestation_valid_through` is body-only, stored as `influence_attestation_valid_through`); grep for `strftime`/`isoformat`/`%Y` outside `clock.py` (none — no ad-hoc date formatting, e.g. tracking labels use `manufacture_date_month`, a plain string); `routes/products.py:163-178` compliance summary (no datetime members); `validation.datetime_field` → `clock.parse_iso8601`; `labs.py:74` (the one post-creation rewrite of a client instant, still client-sourced).
(c) Adjustment: made "every **other** datetime-valued field" the governing universal with the list illustrative, so unlisted fields are not excluded; said "non-zero sub-second component" rather than "milliseconds present" so a supplied `.000123` correctly renders `.000Z`; said "truncated toward zero" not "rounded"; deliberately omitted any claim about how offsets/naive inputs are parsed (out of scope and would have over-claimed); phrased the client-instant clause as "the same instant" rather than "the same string" because `to_utc` converts non-UTC offsets.

**Edit 2 — §2.4 `current_utc`.**
(a) Subject: the clock endpoint's echoed instant.
(b) Paths enumerated: `routes/clock.py` (sole clock blueprint route — confirmed one endpoint, matching §4 line 381), `clock.set_now`→`to_utc`, `clock.now_iso_instant`, `clock.STARTUP_UTC`/`reset`, plus every `clock.now()` consumer to confirm the reading is never rendered anywhere else (`gates.py`, `calc.py`, `engine.py`, route stampers all store datetimes, which then go through `db.serialize`).
(c) Adjustment: tied the format to the rule stated in edit 1 by reference instead of restating it, and hedged the fractional case to "only when the administrator set an instant that carried one" so an admin-supplied sub-second clock still matches.

**Edit 3 — §3.5 plan-activation precedence.**
(a) Subject: refusal ordering when a plan-axis state check coexists with a product `certification_state` check.
(b) Paths enumerated: `routes/plans.py:96-110` (activation), `routes/plans.py:132-138` (periodic review — plan state only, no product-state check), `routes/orders.py:97-101` (booking — product state *before* plan state), `routes/certificates.py:151-155` (issuance — product state before certificate axis), `routes/certificates.py:84-86` (draft), `routes/products.py:189-191` and `:230-232` (submission, archival), plus a full grep of `ERR_PRODUCT_STATE_INVALID`/`ERR_PLAN_STATE_INVALID`/`ERR_CERTIFICATE_STATE_INVALID`/`guard_not_archived` callsites to confirm activation is the only inversion. Also re-read §3.5 line 275 to confirm the `DRAFT`-or-`RESAMPLE_DUE` activatable set is already pinned there (so §2.11 rank 11's "`DRAFT` for activation" needed no touching).
(c) Adjustment: scoped the reordering sentence strictly to plan activation and added an explicit "the operations rank 9 does cover … are unaffected" clause so the wording cannot be read as globally demoting rank 9; used the existing rank vocabulary rather than introducing a new rank number.

Orchestrator verification: `PRD_FINALIZED.md` is 509 lines / 124,996 chars; `diff` against `PRD.md` shows 6 changed lines total (3 inline edits), confirming the patch is minimal; `.step8_state.md` confirmed absent.

## Step 7 verification (orchestrator-run 8-round parallel sweep) — 2026-09-01T05:32:00.000Z

The orchestrator re-ran the full 8-round parallel stability sweep itself, because the Step 7 subagent left no `results.*.json` on disk. Command was the canonical one (`prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30`, 8 concurrent rounds joined with `wait`, per-round free-port claim, no `--api-url`).

| results file | passed | failed | errors | skipped | total |
|---|---|---|---|---|---|
| results.1.json | 298 | 0 | 0 | 0 | 298 |
| results.2.json | 298 | 0 | 0 | 0 | 298 |
| results.3.json | 298 | 0 | 0 | 0 | 298 |
| results.4.json | 298 | 0 | 0 | 0 | 298 |
| results.5.json | 298 | 0 | 0 | 0 | 298 |
| results.6.json | 298 | 0 | 0 | 0 | 298 |
| results.7.json | 298 | 0 | 0 | 0 | 298 |
| results.8.json | 298 | 0 | 0 | 0 | 298 |

**298/298 in all 8 rounds, zero flakiness — the Step 7 green claim is independently confirmed and the eight evidence files now exist.** `grep -rn "pytest.mark" test_suite/` returns nothing, so the green sweep contains no skipped or xfailed test.

## Step 9: Complete PRD — 2026-09-01T05:52:00.000Z

The walk is complete and `.step9_state.md` has been removed.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2203_children_s_product_testing_certification/workspace/PRD_COMPLETED.md`

| | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` (source) | 509 | 124,996 |
| `PRD_COMPLETED.md` | 512 | 142,702 |
| delta | +3 | **+17,706** |

50 edited/inserted paragraphs, all in-place: **37 ambiguity-pins**, **13 mismatch-revisions**. No new sections; three new lines total (one envelope bullet plus one §2.3 paragraph).

## Changes

**§1/§2.2 envelope**
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9` (length 24) — `response.py:10,14`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so it is constant while the clock stands still — `response.py:20`
- §2.2 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` at HTTP **404**, disallowed method at HTTP **405** (not the 400 §5 tabulates); trailing slash insignificant — `app.py:30,51-61`

**§2.3 pagination/lists**
- §2.3 — revise — ambiguity — `created_at` ties keep insertion order; no secondary key — `paging.py:24-33`
- §2.3 — insert — ambiguity — filters are exact-equality and conjoined; id filters shape-checked but never resolved; empty value or out-of-set enum → `ERR_INVALID_REQUEST`; boolean filters accept only the six literals — `paging.py:11-14`, `validation.py:183-202`

**§2.10 / §2.11 refusal ordering**
- §2.10 — revise — **mismatch** — attestation blocks only when `valid_through` is null or **strictly before** the clock; equality still passes — `services/gates.py:13-20`
- §2.10 — revise — **mismatch** — "exactly one" accreditation → **first qualifying row in insertion order**, and that row prices the work; also re-verified at start-testing — `services/gates.py:22-41`
- §2.11 r12 — revise — **mismatch** — furnishing additionally requires `accompaniment_status` `NOT_FURNISHED`; recall has no such condition — `routes/certificates.py:200-212`
- §2.11 r13 — revise — **mismatch** — rank 13 also covers product archival (`ERR_BATCH_STATE_INVALID` on a `RELEASED`/`STOP_DISTRIBUTION` batch) — `routes/products.py:233-235`
- §2.11 r21 — revise — **mismatch** — first-qualifying-row semantics + applies-to extended to taking an order into testing — `services/gates.py:22-41`
- §2.11 r27 — revise — **mismatch** — applies-to extended to ordering a retest round — `routes/cases.py:152-153`
- §2.11 r33 — revise — **mismatch** — applies-to extended to submission for certification, where it is that operation's last check (after ranks 37, 38) — `routes/products.py:203-215`

**§3.1–§3.2 reference data and laboratories**
- §3.1 — revise — ambiguity — duplicate `rule_code` → `ERR_INVALID_REQUEST` (400), not a conflict code — `routes/reference.py:43-95`
- §3.1 — revise — ambiguity — duplicate `category_code` → `ERR_INVALID_REQUEST` (400) — `routes/reference.py:117-149`
- §3.1 — revise — ambiguity — mapping retirement re-derives and bumps each `DRAFT` product without touching gap score or posture; retiring an already-`RETIRED` mapping is accepted — `routes/reference.py:221-237`
- §3.2 — revise — ambiguity — `operational_state` is exactly `{ACTIVE, BARRED}`, set directly with no state precondition — `routes/labs.py:80-89`
- §3.2 — revise — ambiguity — `suspension_reason` is 1–200 chars and is stored on the EXPIRED branch too; a suspension at or before `valid_through` takes the ordinary branch — `routes/labs.py:145-159`
- §3.2 — revise — **mismatch** — the cascade credits `invoice_total_cents` for **every** invalidated order (both `SCHEDULED` and `IN_TESTING`) and bumps the laboratory exactly once; plan hop forces `RESTRICTED` unconditionally; plans not in `ACTIVE` are untouched — `services/engine.py:108-160`

**§3.3 products and bill of materials**
- §3.3 — revise — ambiguity — registration seeds `evidence_path` null, `risk_weighted_gap_score` 0 (not the 100 the empty-rule-set branch would yield), `material_change_count` 0, four distribution counters 0 — `routes/products.py:58-96`
- §3.3 — revise — ambiguity — part addition always bumps the product; re-derivation only in `DRAFT`/`SCOPED`, and derived fields only on the `SCOPED` arm; response is the part with 201 — `routes/products.py:252-288`
- §3.3 — revise — **mismatch** — archival is refused with `ERR_BATCH_STATE_INVALID` (409) right after rank 9; posture is set to `UNSCOPED` directly and gap score is left as-is — `routes/products.py:227-245`

**§3.4 component reliance**
- §3.4 — revise — ambiguity — `COMPONENT_RELIANCE_NOT_ALLOWED` on submission is checked last, after the BoM and rule-set checks, and leaves the product wholly untouched — `routes/products.py:184-225`
- §3.4 — revise — ambiguity — certificate submission bumps the supplier's count and version; the part itself is not touched — `routes/partcerts.py:28-80`
- §3.4 — revise — ambiguity — `reliance_documentation_ref` is a mandatory 1–200-char string on **both** decision branches — `routes/partcerts.py:109-118`
- §3.4 — revise — **mismatch** — RELY has **four** preconditions in impl's order (`ON_FILE` → rule membership → `component_reliance_allowed` → `evidence_path`); the part's own `reliance_status` is **not** a precondition; promotion only from `PENDING` and only with a non-empty applicable rule set — `routes/partcerts.py:127-157`, `services/engine.py:71-90`

**§3.5 sampling plans**
- §3.5 — revise — ambiguity — plan creation has no product-state or evidence-path precondition and does not touch the product; a plan on an empty `required_rule_ids` sizes to the volume-and-base term and lands at the floor — `routes/plans.py:36-69`
- §3.5 — revise — ambiguity — activation re-sizes nothing and never reaches the product (no version bump, no derived recompute) — `routes/plans.py:112-127`
- §3.5 — revise — ambiguity — a null `periodic_due_at` is never due on both arms; lapse forces `SUSPENDED`, re-sizes nothing and retains `resample_trigger`; the deadline instant itself is not yet past — `routes/plans.py:140-162`

**§3.6 test orders**
- §3.6 — revise — ambiguity — the evidence-path collision uses the same single-`RELIED_UPON`-row coverage predicate as the gap score and cannot fire on `FULL_PRODUCT_TEST` or a null path — `routes/orders.py`, `services/calc.py`
- §3.6 — revise — ambiguity — pricing reuses the first-qualifying accreditation; a missing row would yield a 0-bp surcharge but the gate makes it unreachable — `routes/orders.py:41-49`
- §3.6 — revise — ambiguity — booking bumps plan and laboratory by 1 each and mints the order at version 1, leaving the product untouched — `routes/orders.py:70-74`
- §3.6 — revise — ambiguity — `measured_value` is mandatory with no numeric bound (negatives accepted) — `routes/orders.py` report handler
- §3.6 — revise — ambiguity — on a pass the case hop runs **first**, before the product is touched; a non-matching `retest_case_id` is silently skipped; the product bumps unconditionally — `routes/orders.py` report handler
- §3.6 — revise — ambiguity — the fail cascade's four hops touch **no** sampling plan (units stay committed, `last_verified_at`/`periodic_due_at`/`plan_state` unchanged); derived fields refresh once at the end with posture overwritten unconditionally — `services/engine.py:161-227`

**§3.7 certificates**
- §3.7 — revise — ambiguity — a missing `@` in the email and a `manufacture_date_month` not exactly 7 chars are rank-5 shape violations (`ERR_INVALID_REQUEST`), not completeness failures; `expected_product_version` is an integer ≥ 1 — `routes/certificates.py:56-118`
- §3.7 — revise — ambiguity — drafting bumps only the product and recomputes nothing on it; predecessor is the first `ISSUED` row in insertion order; `content_completeness_pct` is computed at draft time — `routes/certificates.py:56-118`
- §3.7 — revise — ambiguity — the SoD evidence set is exactly the `REPORTED_PASS` orders whose `rule_id` is in `cited_rule_ids`; with none, the guard can never trip — `routes/certificates.py:28-40,147-185`
- §3.7 — revise — **mismatch** — furnishing requires `ISSUED` (checked first) **and** `NOT_FURNISHED`; recall requires `FURNISHED` only — `routes/certificates.py:200-224`

**§3.8 batches**
- §3.8 — revise — ambiguity — `tracking_label_compliant` derived from the submitted flags, all four product counters recomputed from batches, product bumped with gap score and posture left alone — `routes/batches.py:44-91`
- §3.8 — revise — ambiguity — coverage is a lower-bound test (checked first) plus UTC year/month equality against `manufacture_date_month`, both bounds inclusive; a `SUPERSEDED`/`WITHDRAWN`/`VOIDED` certificate may be named and its start falls back to `created_at` — `routes/batches.py:26-42`
- §3.8 — revise — **mismatch** — release preconditions run in §2.11 rank order (certificate axis → batch state → posture → label), so the certificate axis outranks even a wrong batch state — `routes/batches.py:139-164`

**§3.9 noncompliance**
- §3.9 — revise — ambiguity — stop-distribution moves only in-scope `HELD`/`RELEASED` batches (an already-stopped batch counts toward `scope_units` but is not rewritten); gap score and posture untouched — `routes/cases.py:65-94`
- §3.9 — revise — ambiguity — retest input shapes/defaults, the plan-must-belong-to-product rule, and the exact precondition order (manufacturer-owned → window → slot → units → budget) — plus the explicit list of checks retest ordering does **not** re-run (barred, attestation, accreditation, plan state, rule applicability), with a missing accreditation contributing a 0-bp surcharge instead of refusing — `routes/cases.py:125-161`
- §3.9 — revise — ambiguity — the escalation branch is decided immediately after the case-state check and bypasses every body-derived precondition; `sample_count`, window and `expedite_requested` are discarded — `routes/cases.py:146-147`
- §3.9 — revise — ambiguity — first-round promotion only fires when the product actually stands in `SUSPENDED`; plan ledger recomputed from source rows; laboratory billed total incremented and bumped — `routes/cases.py:163,187,194-196`
- §3.9 — revise — ambiguity — escalation bumps each destroyed batch, leaves already-`DESTROYED` alone, does **not** rewrite `certification_state`/gap score/posture, and returns the case — `routes/cases.py:200-215`
- §3.9 — revise — ambiguity — corrective action takes `expected_case_version` ≥ 1 and a 1–200-char ref; the state check precedes the version guard; the product is not touched — `routes/cases.py:218-240`
- §3.9 — revise — **mismatch** — closure checks the tracking label **before** segregation of duties (ranks 25 then 26); `DESTROYED` batches are not examined; "no other open case" excludes `CLOSED` and `ESCALATED_RECALL`; the product bumps regardless of a state change — `routes/cases.py:243-260`, `services/engine.py:266-288`

**§3.10 material change**
- §3.10 — revise — ambiguity — a supplied-but-nonexistent `component_part_id` is `ERR_COMPONENT_PART_NOT_FOUND` at rank 6, before the archival guard and the subject-coherence check, for either `subject_type` — `routes/events.py:44-52`
- §3.10 — revise — ambiguity — the product's `version` advances by exactly 1 on **both** branches, cascade or not — `routes/events.py:70-73`

## Coverage: modules walked and found already fully pinned (no edit needed)

`auth.py` (all four gate priorities and their codes already match §2.11 ranks 1–4), `errors.py` (all 56 code→status pairs match §5 verbatim), `refs.py` (per-table not-found codes and the child-of-parent rule already pinned at rank 6), `clock.py` (rendering families, `add_calendar_months` day clamping and startup instant already pinned by the Step 8 §2.4 edits, which I verified intact), `db.py` (audit-stamp vs domain-instant rendering split, version-1-on-insert, `with_version=False` for events — all already stated), `validation.py` (no standalone gap; every default, bound and length it enforces is pinned at its use site instead), `services/calc.py` (all 18 calculations verified formula-by-formula; the only gaps surfaced were at the route sites listed above, chiefly the surcharge-when-unaccredited and rounding-point statements).

Modules that produced edits: `app.py`, `response.py`, `paging.py`, `services/gates.py`, `services/engine.py`, and all eleven route modules (`reference`, `labs`, `products`, `partcerts`, `plans`, `orders`, `certificates`, `batches`, `cases`, `events`, `clock` — `clock.py`'s endpoint needed no new edit beyond the verified Step 8 `current_utc` revision).

All three Step 8 edits were verified present and unmodified (§2.4 timestamp families at line 90, §2.4 `current_utc` at line 92, §3.5 plan-activation refusal order at line 280); two of them I extended rather than replaced.

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 512 lines / 142,702 chars; `.step9_state.md` confirmed absent; all three Step 8 edits confirmed still present in the completed file.

---

# PIPELINE COMPLETE — 2026-09-01T05:53:00.000Z

All nine steps have valid artifacts on disk. Resume run picked up at Step 5 (Steps 1–4 and 6 were verified complete from the crashed run and were not regenerated).
