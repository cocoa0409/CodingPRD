# Worklog — task_0438_plm_eco

Scenario: 438. Product Lifecycle Management (PLM/ECO): part & multi-level BOM revision, engineering change request/order (ECR/ECO), approval & effectivity date, where-used impact analysis, document/CAD vault & release, deviation/waiver, supplier change notice (PCN), serialization/config control

Difficulty band: Expert (§0.4)

## Step 1: Create task directory — 2026-06-20T17:31:47.000Z

Task directory `tasks/task_0438_plm_eco` pre-assigned and already created (workspace/ present). No auto-index scan performed.

## Step 2: Generate scaffold (Expert band) — 2026-06-20T18:00:31.000Z

Generated all three Expert-band scaffold artifacts for task_0438_plm_eco (Product Lifecycle Management / ECO) and verified them with a clean `scaffold_lint.py` run.

Files written (all three required):
- SCAFFOLD.yaml (1553 lines)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1438 lines)
- SCAFFOLD_CORNER_DESIGN.yaml (1434 lines)

Complexity profile: primary archetype `graph_constraint` (multi-level BOM DAG, where-used reverse-closure, cycle detection) + secondary `multi_party_negotiation` (ECR/ECO approval quorum); `graph` topology, `branching` state machines, `segregation_of_duties` role model. Layers: version-pinning-on-approval, scheduled/deferred actions, cascading side effects, optimistic concurrency.

Counts (Expert band §0.4 satisfied):
- Entities: 12 (Supplier, Part, PartRevision, BomLine, ECR, ECO, ApprovalTask, ChangeAffectedItem, Document, Deviation, SupplierChangeNotice, SerializedUnit)
- State machines: 8 (PartRevision, ECR, ECO, ApprovalTask, Document, Deviation, SCN, SerializedUnit — includes a cyclic ECO recall loop and SerializedUnit parallel build×conformance dimensions)
- Concurrency rules: 2 (OCC on Part.version and PartRevision.version, both CREATE-with-supersede races)
- Calculations: 4 (bom_cost_rollup with planned/effective variants, where_used_blast_radius with as-designed/as-released variants, eco_approval_quorum, deviation_coverage)
- Validations: 21 (priority-ordered)
- Endpoints: 68 (incl. one `/_clock` test-driving endpoint, default time 2026-01-01T00:00:00Z)
- Errors: 25 (all triggerable — verified ≥2 mentions each)
- Roles: 6 (Designer, ChangeAdmin, Approver, QualityEngineer, SupplierManager, Viewer — all opaque)

Difficulty design: 18 instances = 9 rules × 2. Corner design: 41 instances (38 active + 3 `excluded_because` stubs).

Verification: all numeric asserts independently computed against the formulas; zero unbound placeholders; zero dangling grounds refs; no forbidden concurrency vocabulary; all OCC versions dynamic `${var}`; neither design key appears in SCAFFOLD.yaml. Final scaffold_lint.py verdict: clean.

## Step 3: Copy INSTRUCTION.md — 2026-06-20T18:00:36.000Z

Copied ./INSTRUCTION.md → tasks/task_0438_plm_eco/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-20T18:05:57.000Z

Generated workspace/PRD.md from the PLM/ECO scaffold (293 lines, 41744 bytes).

Structure: 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue), with 19 subsections total. §2 has 8 domain-derived cross-cutting subsections (RBAC, response structure, pagination, common-properties+logical-clock, cascades/reverts, nested-retrieval, OCC, cost precision); §3 has 11 business-process subsections organized along the graph topology and change pipeline.

Hard contract results (all PASS): field coverage 61/61; rule coverage (validations priority ordering, 2 OCC rejections, all 8 state machines + parallel SerializedUnit dimensions, all 4 calculations with both variants, sibling-branch symmetry); path-purity in §3 (0 path/method tokens). §2.2 emitted verbatim from template. §4 4-column table; §5 2-column table with all 25 error codes.

Confirmation: Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read. No sibling task accessed.

## Step 5: Generate unit tests — 2026-06-20T18:34:27.000Z

Test files: 5 (plus conftest.py), in test_suite/:
- test_01_catalog_and_crud.py (15 tests) — part CRUD, access control, pagination, computed reads
- test_02_state_machines_and_validations.py (15) — transitions, guarded preconditions, BOM cycle, deviation window, RBAC isolation
- test_03_costing_and_where_used.py (10) — dual-variant cost, where-used blast radius, part-type branching, per-line rounding
- test_04_change_pipeline_and_cascades.py (28) — recall cycle, parallel dimensions, depth-3 release cascade, PCN spawn, quorum boundary, priority conflicts, exclusive occupancy, temporal overlap, compensating reverts
- test_05_concurrency_and_scheduled.py (6) — OCC stale-version, clock-gated effectivity/expiry, deviation coverage cap

Total: 74 tests, 74 Design tags (each test exactly one tag — no untagged/dual-tagged/broken-pointer tags).

Queue A (Difficulty): all 18 instances translated, each with ≥2 tests (38 tests total). One instance — priority_pair_validation_conflict/state_beats_referential_on_make_effective — keeps required outcome via validate_error_is_one_of([ERR_INVALID_STATE, ERR_ECO_NOT_APPROVED]) (error-precedence silence pattern). No difficulty instance fully skipped.

Queue B (Corner): 36 of 38 non-stub instances translated (1 test each). 3 excluded_because stubs not translated. Skipped: 2 instances, both PRD-coverage failure (Silence): state_machines/submit_review_from_in_review_invalid_state and state_machines/terminal_state_obsolete_locked — PRD never names ERR_INVALID_STATE in prose for these transition violations. Gaps left as gaps.

test_helpers files written (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

## Step 6: Generate implementation — 2026-06-20T18:34:27.000Z

Built Python + Flask implementation in workspace/implementation/ (7 modules + launcher + deps):
- start.sh — foreground launcher, exec python3 app.py, guarded pip install
- requirements.txt — flask==3.0.3
- app.py — all 68 routes, error handlers, auth/RBAC, validation ordering
- db.py — in-memory Store (12 dicts keyed by id) + logical clock
- errors.py — ApiError + 25-entry error catalogue with HTTP statuses
- response.py — success/error envelope helpers (meta/response_type/data, req_ ids, ISO-8601 UTC ms timestamps)
- middleware.py — X-User-ID/X-User-Role extraction, six-role RBAC
- common.py — common fields (id/created_at/updated_at/version), mutation touch, input parsing, pagination
- services.py — calculations + state-machine cascades

Endpoint count: 68 (29 GET + 39 POST) — matches PRD §4 table.

Logical clock (/plm/_clock/set_current_utc): single datetime on per-process Store, init 2026-01-01T00:00:00Z; only repositions, never auto-fires effectivity/expiry. Resets on every start.sh reboot.

Hard constraints confirmed: in-memory only (no SQLite/JSON/tmp/disk; reboot test verified); no seeded/hardcoded data; start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec. make-effective on non-APPROVED ECO returns ERR_ECO_NOT_APPROVED per error-catalogue condition.

## Step 7: Run tests and iterate — 2026-06-20T18:39:39.000Z

Iterations run: 2 (1 diagnostic sweep + 1 confirming sweep).

Initial state: Each of the 8 rounds reported 73/74, with a single consistent failure — test_unknown_input_field_revision_count_rejected — failing in all 8 rounds. No flakiness; the other 73 tests passed in every round.

Tests deleted (1):
- test_unknown_input_field_revision_count_rejected (test_suite/test_01_catalog_and_crud.py) — PRD-SILENCE / DEFAULT-VALUE (unknown-field) SILENCE. The test sent a Part-create payload with the system-computed field revision_count: 99 and asserted ERR_INVALID_REQUEST. The PRD never states that unknown or system/computed input fields are rejected; Section 2 has no strict-input rule and ERR_VALIDATION/ERR_INVALID_REQUEST are scoped only to pagination bounds, duplicate codes, supplier-linkage mismatch, and negative base_cost_cents. The cited PRD sentences ("On creation the part's revision_count is 0... a computed count of the part's revisions") describe computed output and are equally satisfied by a faithful implementer that simply ignores the extra field and computes revision_count as 0 — failing STEP 1b unique-derivability. The driving scaffold rule (Corner/entities/system_fields_input_ignored) is even named "input_ignored," confirming the intended behavior is to ignore, not reject; the test mistranslated "ignored" into "rejected."

Fixes applied to test_helpers/: None.
Fixes applied to implementation/: None. The implementation already correctly ignores unknown input fields and computes revision_count, consistent with the PRD.

Final result: Clean 8-round parallel sweep — all 8 rounds 73/73, 0 failures, 0 errors, no flakiness.

## Step 8: Finalize PRD — 2026-06-20T18:42:27.000Z

Produced workspace/PRD_FINALIZED.md. Line counts: PRD.md = 293, PRD_FINALIZED.md = 295. Delta: +2 lines (+0.68%). One edit (one inserted paragraph).

Changes (1):
- Section 2.2 (API Response Structure) — insert — added a system-wide rule that write endpoints read only their explicitly-defined input fields and silently ignore any unknown / system-computed / server-owned field (no strict-input rule; no error raised), with the server always computing such values itself — common.py:43-104 (get_json, require_str, optional_int, etc.), app.py:210-244 (create_part), app.py:241,307 & services.py:283,325-327 (revision_count always server-computed).

Per-edit pre-edit search log:
- (a) Subject: how create/mutation endpoints handle unknown, extra, and system-computed input fields (the PRD-silence exposed by deleted test test_unknown_input_field_revision_count_rejected).
- (b) Impl paths enumerated: common.py input helpers (all do body.get / field in body, none inspect for extra keys); grepped app.py/services.py/common.py for keys()/not in/allowed_fields/strict/unknown/extra — no strict-field rejection anywhere; create_part/create_revision and all other create endpoints read only named fields; revision_count is server-owned (set 0 at create, recomputed from revisions_of_part). Behavior uniform across all write endpoints.
- (c) Wording adjustment: phrased globally ("every write endpoint", "any other property"); listed concrete fields as examples only; named both ERR_INVALID_REQUEST and ERR_VALIDATION plus "or any other error"; did not claim server echoes/stores ignored fields.

Genuine PRD silence pinned; no other Step 7 items existed.

## Step 9: Complete PRD — 2026-06-20T18:46:00.000Z

Produced workspace/PRD_COMPLETED.md. Source PRD_FINALIZED.md (295 lines, 42,322 chars) → PRD_COMPLETED.md (295 lines, 43,862 chars). Char delta +1,540; line count unchanged (all in-paragraph inserts/revisions; no new sections).

Change counts: 7 changes — 7 ambiguity-pins, 0 mismatch-revisions.

Per-change bullets:
- §2.1 RBAC — insert — ambiguity — X-User-Role outside the six recognized roles is malformed → ERR_MISSING_AUTH_HEADER (401), before any role-permission check — middleware.py:35-36
- §2.3 Pagination — insert — ambiguity — non-integer-parseable limit/offset → ERR_VALIDATION; empty value falls back to default — common.py:121-128
- §2.5 Cascades — insert — ambiguity — general rule: a state-transition action on a resource not in the required source state, where no more-specific error is named, → ERR_INVALID_STATE (uniform across revision/document/ECR/ECO/deviation/PCN/unit guards) — app.py (many guard sites)
- §3.4 Where-used — revise — ambiguity — direct_parent_revision_ids is deduplicated and ordered by consuming BOM lines' created_at ascending — services.py:139-145
- §3.5 ECO population — insert — ambiguity — attaching affected items / approval tasks requires order DRAFT (else ERR_INVALID_STATE); DRAFT check precedes already-governed check; "non-terminal" = DRAFT/IN_APPROVAL/APPROVED — app.py:599-607,652-653; services.py:223
- §3.6 Approval decision — insert — ambiguity — task's own decision must be PENDING (else ERR_INVALID_STATE), evaluated between IN_APPROVAL state check and assignee check — app.py:725-726,750-751
- §3.7 Make-effective — insert — ambiguity — requires status == APPROVED (else ERR_ECO_NOT_APPROVED), evaluated before the clock gate — app.py:770-775

Post-step cleanup (orchestrator): Removed stray trailing `</content>` and `</invoke>` tool-call artifact lines that the Step 4 doc-generator had captured into PRD.md and which `cp` had propagated into PRD_FINALIZED.md and PRD_COMPLETED.md. All three files now end cleanly with the §5 error-code table (PRD.md 291 lines; PRD_FINALIZED.md & PRD_COMPLETED.md 293 lines each). No prose content affected.
