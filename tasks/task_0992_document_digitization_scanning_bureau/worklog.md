# Worklog — task_0992_document_digitization_scanning_bureau

Scenario: Document Digitization & Scanning Bureau: intake & box/inventory, prep & scan/OCR pipeline, indexing & metadata, secure destruction/return, cloud delivery & access, rush & per-page, chain-of-custody (HIPAA), retention

Difficulty parameter: "generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-10T11:44:00.000Z

Pre-assigned output folder `tasks/task_0992_document_digitization_scanning_bureau` with `workspace/` subdirectory already existed per command args; Step 1 auto-index scan skipped as instructed. Directory verified present.

## Step 2: Generate Scaffold — 2026-08-10T12:44:00.000Z

Scaffold generation complete for task_0992 (Document Digitization & Scanning Bureau). All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_0992_document_digitization_scanning_bureau/` and lint-clean.

**Output files**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Counts**
- Entities: **15** (Client, ServiceAgreement, Batch, Box, Document, ScanSession, PageLog, IndexRecord, AccessGrant, CustodyEvent, DestructionCertificate, ScannerUnit, ShelfSlot, ShelfAssignment, Invoice)
- State machines: **7** (Batch 8-state cyclic-rework pipeline + parallel `delivery_status` dimension; Box 9-state branching disposition; Document with system-driven REJECTED branch; ScanSession; AccessGrant with lazy expiry; Invoice; ShelfAssignment)
- Calculations: **5** (invoice_pricing dual-variant tiered pricing with pinned per-document rounding; storage_fee_projection dual-variant with whole-day floor; batch_indexability with nested max(1, floor(10%)) allowance; custody_segregation_check chronological adjacency; rush_capacity_window threshold)
- Validations: **13** priority-ordered rows (auth → existence → request shape → client state → entity state → safety → temporal → referential → constraint → fiscal)
- Endpoints: **77** (flat topology under `api_prefix: /`, sub-resource GETs with literal `{id}` parents for FK reverse-reachability, one test-driving `POST /_clock/set_current_utc` with mandatory default `2026-05-01T00:00:00Z`)
- Errors: **36** catalog codes, all referenced by at least one validation/transition/concurrency rule
- Roles: **10** (PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk — all `opaque`; ClientUser — `entity_backed:Client`)
- Difficulty-design instances: **18** (exactly 2 per each of the 9 §0.5 rules)
- Corner-design instances: **49** (46 active + 3 `excluded_because` stubs citing §1.8 instances), across all nine claim-extraction-guide sections

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (77 endpoints, 15 entities, 18+46 instances, 942 calls scanned)

**Notable design decisions**
- **Flat topology** (not hierarchical) chosen deliberately — the lint's FK reverse-reachability check requires sub-resource GETs with a literal `{id}` parent placeholder, so all resources are peers joined by FKs; this also matches the skill's PRIORITIZE-flat guidance.
- **Segregation of duties** as the role model, enforced two ways: adjacency check on the custody chain (same user may not author consecutive custody events on a box; system-generated events serve as prior links but are never themselves rejected) and witness != recorder on destruction certificates.
- **Dual-variant divergence is genuinely falsifiable**: provisional invoice pricing includes REJECTED documents' produced pages while the final variant removes them (6075 vs 5625 cents in the pinned fixture); storage projection shrinks after box return while the issued invoice stays frozen (0 vs 110 cents).
- **Count-once ledger**: `scanned_pages` accumulates produced material across rework (200) while `billable_scanned_pages` and the invoice stay conserved (100 / 4500 cents) — the compensating-invariant anchor.
- **Two overlap regimes with different interval semantics**: scanner half-open point-occupancy (busy until `ended_at`) vs shelf aggregate-weight capacity over the ACTIVE assignment set.
- **Cascade depth-3 chains**: clock → Batch sweep → Box disposition → ShelfAssignment release + slot debit; and scan commit → Document scan → Batch aggregates → DRAFT invoice recompute.
- **Compliance cascade**: any destruction flags all sibling non-final boxes client-wide (`custody_flagged`), gating custody/destruction until a ComplianceOfficer clears — a fourth role in the segregation web.
- All 942 recipe calls replay from empty DB with placeholder closure; every numeric assert is a precomputed literal (e.g., 6075/5625, 106 vs the forbidden 105 sum-then-round, 110-cent storage accrual at the day-12 boundary).

## Step 3: Copy Shared Files — 2026-08-10T12:45:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0992_document_digitization_scanning_bureau/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T12:50:00.000Z

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_0992_document_digitization_scanning_bureau/workspace/PRD.md`

**PRD line count:** 291 lines

**Section list:**
- `# Document Digitization & Scanning Bureau API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Resource Identity and Common Properties
  - 2.5 The Logical Clock
  - 2.6 Monetary Precision and Rounding
  - 2.7 Optimistic Concurrency Control on the Batch Ledger
  - 2.8 Validation Ordering
  - 2.9 Nested Resources and Existence
- `## 3. Business Logic & Workflows`
  - 3.1 Client Onboarding and Service Agreements
  - 3.2 Batch Intake and Box Shelving
  - 3.3 Preparation, Scanning, and the Session Ledger
  - 3.4 Quality Review and the Rework Loop
  - 3.5 Indexing, Metadata, and Rejection
  - 3.6 Delivery, Pricing, and Invoicing
  - 3.7 Retention, Disposition, and Certified Destruction
  - 3.8 Client Access, Grants, and Download
- `## 4. Endpoint Definitions` (77-row table, 4 columns)
- `## 5. Error Code Catalogue` (36-row table, 2 columns)

**Coverage counts:**
- Entities: 15 (Client, ServiceAgreement, Batch, Box, Document, ScanSession, PageLog, IndexRecord, AccessGrant, CustodyEvent, DestructionCertificate, ScannerUnit, ShelfSlot, ShelfAssignment, Invoice)
- Entity fields covered: 68/68 (64 declared + 4 common)
- Endpoints covered: 77/77 (every scaffold endpoint appears in §4 table)
- Errors covered: 36/36 (every error ID appears in §2/§3 prose and in §5 table)
- Request-body params: 38/38; query params: 6/6; path params: 2/2
- State transitions expressed: 33/33; calculations expressed: 5/5; validation priorities: 13/13; OCC rules: 1/1

**Coverage-audit verdicts:**

Field coverage check: 68/68 fields, 38/38 request bodies, 6/6 query params, 2/2 path params — PASS.
Rule coverage check: 13/13 validations, 1/1 OCC, 33/33 transitions, 5/5 calculations, 77/77 side effects, 64/64 structured fields, 4/4 sibling-branch symmetry — PASS.
Path purity check (§3 only): 381 backtick tokens, 0 path leaks — PASS.

All three hard contracts report PASS.

## Step 5: Generate Unit Tests — 2026-08-10T13:25:00.000Z

### test_helpers file list
- `test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `test_helpers/types.py` — UserRole + 14 status enums + 16 entity TypedDicts (PageLog/CustodyEvent TypedDicts omit `updated_at`/`version` per append-only common_fields:false)
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~70 methods)
- `test_helpers/api_errors.py` — 36 `ApiErrorId` values + `HTTP_STATUS_CODES` map + `set_error_http_status_map` registration
- `test_helpers/assertions.py` — `assert_<entity>()` for all 16 entities
- `test_helpers/factories.py` — payload factories (input fields only)
- `test_helpers/constants.py` — `CLOCK_STARTUP_DEFAULT`, page rates, `MIN_OCR_CONFIDENCE=70`, `RUSH_ADMISSION_LIMIT=3`
- `test_helpers/test_users.py` — `TEST_USERS` shared constants + `make_<role>_headers()` builders; ClientUser is entity-backed (takes client_id)
- `test_helpers/fixtures.py` — tier 1-3 composite fixtures (create_client_with_agreement, batch_in_intake/scanning/qa/indexing/delivered, scan_and_commit, deliver_and_sweep, destroy_box, etc.)

### test_suite file list and per-file test counts (total 82)
```
 6  test_01_dual_variant_pricing.py
 5  test_02_indexability.py
 5  test_03_page_ledgers_rework.py
 7  test_04_disposition_and_fork.py
 4  test_05_scan_cascade_occ.py
 6  test_06_validation_priority.py
 5  test_07_capacity_boundaries.py
 8  test_08_cross_entity_gating.py
 6  test_09_resource_overlap.py
 2  test_10_batch_state_machine.py
 7  test_11_scan_session_lifecycle.py
 2  test_12_indexing_metadata.py
 4  test_13_invoices_payments.py
 6  test_14_entities_crud.py
 2  test_15_custody_segregation.py
 1  test_16_endpoints_pagination.py
 1  test_17_scope_isolation.py
 3  test_18_rbac.py
 2  test_19_consistency.py
```

### Test counts per queue
- **Queue A (Difficulty)**: 36 tests across 18 instances (≥2 per instance — exactly 2 each)
- **Queue B (Corner)**: 46 tests across 46 non-stub instances (≥1 per instance — exactly 1 each)

### Per-instance disposition

**Queue A — all 18 instances EMITTED** (no skips):
- dual_variant_calc / invoice_pricing_provisional_includes_rejected_final_excludes → 2 tests
- dual_variant_calc / storage_fee_projected_vs_frozen_at_issue → 2 tests
- combinatorial_formula / indexability_nested_allowance_floor_mode_a → 2 tests
- combinatorial_formula / per_document_rounding_before_sum_mode_b → 2 tests
- non_linear_state_machine / batch_qa_rework_cycle_loop → 2 tests
- non_linear_state_machine / box_disposition_branch_fork_return_vs_destroy → 2 tests
- transitive_cascade / clock_sweep_cascade_batch_box_shelf → 2 tests
- transitive_cascade / scan_commit_bubbleup_cascade_document_batch_invoice → 2 tests
- priority_pair_validation_conflict / state_precondition_beats_witness_segregation → 2 tests
- priority_pair_validation_conflict / vault_zone_safety_beats_shelf_capacity → 2 tests
- boundary_precision_check / rush_admission_boundary_at_limit → 2 tests
- boundary_precision_check / shelf_capacity_equality_admitted_over_by_one_rejected → 2 tests
- cross_entity_state_dependency / scan_session_gated_by_batch_state → 2 tests
- cross_entity_state_dependency / download_gated_by_document_delivery → 2 tests
- resource_temporal_overlap / scanner_occupancy_half_open_interval → 2 tests
- resource_temporal_overlap / shelf_aggregate_capacity_overlap_and_release → 2 tests
- compensating_invariant / shelf_occupancy_conservation_occupy_then_release → 2 tests
- compensating_invariant / billable_pages_count_once_across_rework → 2 tests

**Queue B — all 46 non-stub instances EMITTED** (no skips):
- entities: client_creation_defaults_and_system_fields, get_nonexistent_batch_returns_not_found, create_document_missing_required_pages_returns_invalid_request, create_batch_with_computed_field_extra_field_rejected, page_log_append_only_immutability, document_enum_type_constraint_rejected (6)
- state_machines: batch_initial_state_and_invalid_transition_from_intake, batch_terminal_lockdown_closed_rejects_all_actions, index_records_on_unscanned_document_returns_invalid_state, session_void_then_commit_returns_invalid_state, invoice_void_then_issue_returns_invalid_state, qa_review_side_effect_flips_only_target_document (6)
- calculations: indexability_allowance_exceeded_blocks_deliver, storage_free_window_day_boundary, rush_multiplier_not_applied_to_standard_batch, custody_segregation_adjacent_actor_rejected (4)
- validations: request_missing_auth_headers_returns_unauthenticated, suspended_client_mutation_blocked_before_state_checks, metadata_incomplete_rejected, page_log_document_from_other_batch_returns_not_found, witness_segregation_equal_ids_rejected (5)
- endpoints: list_batches_pagination_defaults_and_envelope, download_scope_metadata_only_blocked, grant_expiry_lazy_transition, grant_revoke_blocks_download, vault_only_grant_blocks_public_download (5)
- errors: error_scanner_over_capacity_at_commit, error_empty_scan_session_commit, error_open_session_blocks_submit_qa, error_max_boxes_exceeded, error_second_agreement_rejected, error_return_window_expired_after_sweep, error_branch_exclusivity_return_committed_vs_not, error_documents_incomplete_blocks_submit_qa_and_pass_qa, error_fail_qa_not_reworkable, error_scanner_unavailable_maintenance, error_payment_overpay_and_partial_then_full, error_payment_on_draft_invoice, error_issue_before_delivery, error_custody_flag_blocks_and_compliance_clear_releases (14)
- rbac: indexer_cannot_create_batches_forbidden, client_user_cross_tenant_read_forbidden, segregation_of_duties_role_exclusive_chain (3)
- cross_cutting_layers: occ_stale_version_commit_rejected_then_fresh_succeeds, derived_fields_reconciled_immediately_on_commit (2)
- consistency_model: immediate_consistency_mutation_visible_in_next_read (1)

**Queue B stubs — NOT translated (3)** (verified: each `excluded_because.difficulty_instance` resolves to a real §1.8 instance):
- cross_cutting_layers / draft_invoice_provisional_recompute_covered → owned by Difficulty/transitive_cascade/scan_commit_bubbleup_cascade_document_batch_invoice
- cross_cutting_layers / disposition_sweep_side_effects_covered → owned by Difficulty/transitive_cascade/clock_sweep_cascade_batch_box_shelf
- cross_cutting_layers / cascade_side_effect_chain_covered → owned by Difficulty/transitive_cascade/scan_commit_bubbleup_cascade_document_batch_invoice

### Stage-check verdicts
- pytest collect-only: **PASS** — `82 tests collected in 0.08s`, no import errors.
- Per-instance coverage: 18/18 Difficulty instances ≥ 2 tests; 46/46 non-stub Corner instances ≥ 1 test; 0 stub leaks; 0 orphaned Design tags.
- Docstring tag: every test's docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line (verified via regex sweep).
- PRD citation verbatim check: every PRD §-quoted sentence in every docstring survives a literal whitespace-normalized grep of PRD.md (0 failures across all 82 tests).
- No `pytest.mark.skip` / `skipif` / `xfail` present anywhere in test_suite.

(Note: the first Step 5 subagent run wrote test_helpers/ and the plan but ended before writing test files; it was resumed via SendMessage and completed all 19 test files in the second run.)

## Step 6: Generate Implementation — 2026-08-10T13:25:00.000Z

## File list
```
workspace/implementation/
├── start.sh                 # guarded pip install + exec python3 app.py, $PORT/0.0.0.0
├── requirements.txt         # flask
├── app.py                   # Flask entry, blueprint registration, error handlers
├── db.py                    # in-memory Store, empty dicts + logical clock default 2026-05-01T00:00:00Z
├── errors.py                # ApiError + all 34 error-ID constants
├── response.py              # meta/response_type/data envelope, pagination meta, ISO8601 3-fractional-digit timestamps
├── middleware.py            # X-User-ID/X-User-Role auth, 10-role RBAC, ClientUser subtree scoping
├── util.py                  # id/timestamp helpers, body validation, field type/enum/range guards
├── routes/
│   ├── clock.py             # POST /_clock/set_current_utc + disposition sweep; scanner-units; shelf-slots
│   ├── clients.py           # clients CRUD/suspend/reactivate, service-agreements, client-scoped grants/invoices/batches lists
│   ├── batches.py           # batch create (+auto DRAFT invoice, rush admission), 7 pipeline transitions, 9 sub-resource lists, qa-reviews
│   ├── boxes.py             # box intake (+auto-intake custody event), custody-events, request-return, begin-destruction, certificates, mark-returned, shelf-assignments, documents
│   ├── documents.py         # document get, index-records submit (INDEXED/REJECTED fork), page-logs
│   ├── scan_sessions.py     # session open/page-logs/commit(OCC)/void
│   ├── grants.py            # access-grant get/revoke/documents/download with lazy expiry
│   └── invoices.py          # invoice get (DRAFT recompute)/issue/payments/void
└── services/
    ├── pricing.py           # tiered per-page pricing (per-doc round-half-up then sum), storage accrual, indexability, rush window
    ├── custody.py           # custody trail, segregation check, shelf release, destruction cascade, disposition sweep
    └── serializers.py       # entity views incl. computed projected_storage_fee_cents on batch reads
```

## Endpoint count
77 route registrations covering all 77 rows of the SCAFFOLD §1.5 endpoint table.

## Major subsystems implemented
- **State machines**: Batch (8-state pipeline with cyclic QA→SCANNING rework loop + parallel delivery_status dimension), Box (9-state branching disposition lifecycle), Document (6-state with SCANNED→INDEXED/REJECTED fork on ocr_confidence<70), ScanSession (OPEN/COMMITTED/VOIDED), AccessGrant (ACTIVE/REVOKED/EXPIRED lazy), Invoice (DRAFT/ISSUED/PARTIALLY_PAID/PAID/VOID), ShelfAssignment (ACTIVE/RELEASED).
- **Calculations**: dual-variant invoice pricing (provisional set includes REJECTED+QA_FAILED; final set excludes REJECTED; per-document `Decimal` round-half-up on pages×rate×100 then sum; VOLUME 0.30 / STANDARD 0.45 base with RUSH rush_multiplier), tiered storage accrual (floor whole days since delivered_at minus storage_free_days, floored at 0, ×daily rate, over STORED/SCAN_COMPLETE/AWAITING_DISPOSITION boxes; projected vs frozen-at-issue variants), batch indexability (≥1 doc, all terminal, REJECTED ≤ max(1, floor(10%))), rush capacity window (limit 3, >= comparison), custody segregation (exact-match adjacency vs greatest-created_at event).
- **OCC**: `expected_batch_version` on scan-session commit → ERR_STALE_VERSION 412; only endpoint accepting a version field.
- **Logical clock**: `db.current_utc`, startup default 2026-05-01T00:00:00Z, never wall-clock for domain timestamps; `POST /_clock/set_current_utc` advances and fires the DELIVERED→DISPOSITION_PENDING sweep (boxes→AWAITING_DISPOSITION, ACTIVE shelf assignments released, slot weight debited, batch version bumped).
- **Custody/chain-of-custody**: auto-intake event at box creation; explicit PREP/SCAN/STORAGE hand-offs with role pairing (PrepTechnician/ScanOperator/IntakeClerk), adjacency segregation (422), custody-flag gate (409); system events (STORAGE at shelving, DESTRUCTION, RETURN) recorded as prev links but never rejected; witness segregation (ERR_WITNESS_SEGREGATION); client-wide custody_flagged cascade on certified destruction; ComplianceOfficer clear-custody-flag.
- **Invoicing**: DRAFT auto-created with batch; provisional recompute on every commit and DRAFT read; final pricing locked at delivery; storage frozen at issued_at; payments with balance cap (422) and payable-state gate (ERR_INVOICE_NOT_ISSUED 409); void with reason.
- **Vault/HIPAA**: vault-zone placement for PHI boxes of hipaa_covered clients (422), server-computed vault_only on grants, vault_only + FULL_IMAGE scope + DELIVERED doc + active grant + non-suspended client guards on download.
- **Validation ordering** per PRD §2.8: auth → forbidden → not-found → body well-formedness → client-suspended → state → segregation/custody-flag/vault-scope → temporal → metadata → capacity → fiscal.

## Boot smoke test result
PASS. `PORT=18732 bash start.sh` booted in <1s; unauthenticated request → 401 ERR_UNAUTHENTICATED in correct envelope; empty list → `response_type:"array"` with limit/offset/total_count/has_more meta; clock default confirmed `2026-05-01T00:00:00.000Z`; client created 201 with id/created_at/updated_at/version. A second end-to-end run (client→agreement→batch→box→document→prep→scan→session→page-log→commit) returned 200s throughout; batch showed scanned_pages=10, billable=10, version 4 after commit; DRAFT invoice recomputed to page_subtotal_cents=450 (10 pages × $0.45 STANDARD). Server shut down cleanly. Store starts empty on every boot — no seeding anywhere.

## Step 7: Run Tests and Iterate — 2026-08-10T13:58:00.000Z

All 8 rounds are clean: **82/82 passed in every round**. The loop is complete.

**Iterations run:** 3 sweeps (69/82 → 81/82 → 82/82 × 8 rounds clean).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses were found.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` `destroy_box` — certificate is now recorded by a distinct DestructionSpecialist (`cert_user="ds-2"`) than the begin-destruction actor. PRD §3.3 states the begin-destruction DESTRUCTION link is recorded with the acting user's id and counts as the previous link for the certificate recording's custody-adjacency check, so the old same-actor helper was correctly rejected with ERR_CUSTODY_SEGREGATION.
- `fixtures.py` `create_scanner_unit` — default `scanner_code` is now a unique generated value instead of the fixed "SCN-1" (PRD §3.3: scanner_code is unique); the shared default collided whenever a test needed two units (test_09 ×2, test_17).

**Fixes applied to `test_suite/`:**
- `test_04_disposition_and_fork.py` — two inline destruction sequences (`test_destroy_branch_mints_certificate_and_closes_batch`, `test_destruction_cascade_flags_sibling_boxes_compliance_clears`) now record the certificate as ds-2 (same §3.3 adjacency rule); two timestamp assertions (`destroyed_at`, `released_at`) corrected to the three-fractional-digit form §2.4 mandates (`.000Z`).
- `test_14_entities_crud.py` `test_new_client_active_version_one_clock_default` — `created_at` assertion corrected to `"2026-05-01T00:00:00.000Z"` (§2.5 clock default serialized per §2.4's three-fractional-digit rule).
- `test_15_custody_segregation.py` `test_witness_equal_to_recorder_rejected` — begin-destruction moved to ds-2 so only the witness-equals-actor condition fires; §2.8 orders custody segregation (tripped by the old setup) before witness segregation.

**Fixes applied to `implementation/`:**
- `routes/scan_sessions.py` `commit_session` + `routes/batches.py` `qa_review` + `services/serializers.py` `document_view` — the rework path (QA_FAILED→SCANNED) now uses a committed-pages snapshot taken at QA_FAILED entry instead of comparing logical-clock timestamps; the frozen logical clock made "logs created after QA_FAILED" vacuously false, so reworked documents never re-entered SCANNED (root cause of all three test_03 failures). Snapshot field is stripped from serialized documents.
- `db.py`, `util.py`, `services/custody.py`, `services/serializers.py`, `routes/boxes.py` — added a monotonic `_seq` insertion counter on append-only events; the custody trail's "greatest created_at" adjacency lookup (PRD §3.3 assumes tie-free millisecond timestamps) now breaks frozen-clock ties by insertion order. `_seq` is internal only and popped in serializers.
- `start.sh` — replaced the per-boot `python3 -c "import flask"` preflight with a filesystem probe, cutting a full interpreter startup from each of the ~656 per-test server reboots per sweep. This eliminated the 15s health-poll misses ("API server could not be restarted") seen in sweep 2 under contention from a co-tenant sweep on the shared 8-core host; sweep 3 ran 8/8 clean while that co-tenant load was still active.

Orchestrator verification: all 8 `results.{1..8}.json` files confirm 82/82 passed.

## Step 8: Finalize PRD — 2026-08-10T14:05:00.000Z

Both files are 291 lines (0% delta; four in-place sentence revisions on lines 70, 118, 124, 132).

**Produced:** `workspace/PRD_FINALIZED.md` — 291 lines vs PRD.md's 291 lines (0.0% line-count delta; 4 sentences revised inline, no sections added).

### Changes

- **§3.3 (custody adjacency, line 118)** — revise — replaced "the box's custody event with the greatest `created_at`, and per-box serialization with millisecond timestamps makes ties impossible" with "the box's most recently recorded custody event — greatest `created_at`, simultaneous values broken in favor of the event recorded later, since under the logical clock `created_at` ties are routine" — `implementation/services/custody.py:27-46` (`box_custody_trail` sorts by `_seq`, `check_custody_segregation` reads `trail[-1]`).
- **§3.4 (rework mechanism, line 132)** — revise — pinned how "after the document entered `QA_FAILED`" is measured: a snapshot of the cumulative committed-page total taken at QA_FAILED entry, because frozen-clock timestamps cannot express "after" — `implementation/routes/batches.py:424-429` (`qa_failed_committed_pages` snapshot), `implementation/routes/scan_sessions.py:222-230` (delta comparison).
- **§3.3 (commit coverage, line 124)** — revise — on the rework path from `QA_FAILED`, only pages committed after QA_FAILED entry count toward coverage — `implementation/routes/scan_sessions.py:222-230`.
- **§2.3 (list ordering, line 70)** — revise — pinned the sort tiebreak: `id` fallback on `created_at` ties, except a box's custody trail which is emitted in event-recording order — `implementation/routes/batches.py:136,300,319,332,347,359,371,384,399`, `routes/boxes.py:299,383,472`, `routes/clients.py:172,197,213,271`, `routes/clock.py:74,114,154,180`, `routes/documents.py:113,137`, `routes/grants.py:98`, `routes/scan_sessions.py:140` all use `(created_at, id)`; custody trail uses `_seq` at `routes/boxes.py:216`, `services/serializers.py:122-125`, `services/custody.py:27-32`; `_seq` stripped from responses at `services/serializers.py:43-46,57-60`.

### Items from `<step_7_diff>` with no PRD edit (and why)

- `fixtures.py` `destroy_box` (certificate recorded by ds-2): pure fixture bug — PRD §3.3/§3.7 already pinned the adjacency rule that rejected the old same-actor helper.
- `fixtures.py` `create_scanner_unit` (unique default `scanner_code`): pure fixture bug — PRD §3.3 already states `scanner_code` is unique (`implementation/routes/clock.py:56-58`).
- `test_04` timestamp assertions (`.000Z`) and `test_14` `created_at` default: PRD §2.4/§2.5 already pin three-fractional-digit serialization and the `2026-05-01T00:00:00Z` default (`implementation/response.py:20-28`).
- `test_15` begin-destruction moved to ds-2: PRD §2.8 already orders custody segregation before witness segregation (`implementation/routes/boxes.py:265-272` confirms that order).
- `start.sh` preflight probe: operational/test-harness change, invisible to API behavior — out of PRD scope.

### Pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit 1 (§3.3 adjacency tiebreak).** (a) Subject: how the "immediately preceding custody event" is selected. (b) Enumerated every path touching custody-trail ordering: `services/custody.py:27-46` (trail sort + adjacency check), `services/custody.py:12-24` (`append_custody_event`, the only CustodyEvent factory — called from `routes/boxes.py:117` auto-intake, `:205` hand-off, `:245` begin-destruction, `:319` mark-returned, `:369` shelf placement), `routes/boxes.py:209-219` (GET custody-events, sorts by `_seq`), `services/serializers.py:122-125` (`box_custody_events` helper), `util.py:39-44` (`make_event`, only PageLog/CustodyEvent factory), and grep-verified no other route creates custody events or reads "latest" custody state. (c) Original draft said "the latest event is the most recently recorded one"; revised to keep "greatest `created_at`" as primary with insertion-order tiebreak, because the PRD sentence also underpins the custody-trail GET's "chronological" claim (§4 line 217) — the final wording covers both the check and the listing without redefining "chronological" elsewhere.

**Edit 2 (§3.4 rework measurement).** (a) Subject: which pages count toward a QA_FAILED document's re-coverage. (b) Enumerated: `routes/batches.py:405-431` (`qa_review`, sets snapshot), `routes/scan_sessions.py:155-165` (`committed_pages_for_document`, COMMITTED-only, used for both REGISTERED and QA_FAILED legs), `:202-230` (commit transitions, including `billable_scanned_pages` count-once behavior and `qa_failed_committed_pages` pop), `services/serializers.py:33-36` (snapshot field stripped from output), `services/pricing.py` ledgers (read earlier in session for the §3.3 ledger paragraph — unchanged by this fix). Also verified the REGISTERED first-scan path still uses raw cumulative totals (edit explicitly scopes "committed after QA_FAILED entry" to the rework leg only). (c) Wording avoids naming the internal field `qa_failed_committed_pages`; describes it behaviorally as "the cumulative committed-page total captured at the moment the document entered QA_FAILED" so the no-unknown-server-keys rule (§2.8) and the serialized document shape (§3.3/§4) stay accurate.

**Edit 3 (§3.3 commit coverage).** (a) Subject: commit-time document transitions. (b) Enumerated same paths as Edit 2 plus `services/pricing.py` page-subtotal document sets (provisional set includes QA_FAILED — consistent, since a QA_FAILED doc not yet rescanned remains billable). (c) No adjustment needed; the parenthetical is scoped strictly to the QA_FAILED leg and matches `scan_sessions.py:222-230`.

**Edit 4 (§2.3 sort tiebreak).** (a) Subject: list-endpoint ordering. (b) Enumerated every `items.sort` in the implementation (25 sites listed above under Changes): all non-custody lists use `(created_at, id)`; the three custody-trail paths use `_seq`. Also confirmed `document_view`/`page_log_view`/`custody_event_view` strip internal fields so no new serialized key appears. (c) Original draft pinned only "creation order"; revised to explicitly name the `id` fallback for ordinary lists — because that is what the implementation actually does and leaving it silent would let a fresh implementer pick insertion order and diverge on `GET /batches` etc. — while carving out the custody trail's insertion-order behavior so Edit 1's wording and §4's "chronological" stay consistent.

## Step 9: Complete PRD — 2026-08-10T14:20:00.000Z

All edits applied. Both files are 291 lines (no lines added/removed — all changes are in-paragraph); character count 46720 → 51283 (+4563). 18 paragraphs touched, no new sections.

**Source vs output:** `PRD_FINALIZED.md` (291 lines, 46720 chars) → `PRD_COMPLETED.md` (291 lines, 51283 chars, **+4563 chars**, +0 lines). 18 paragraphs edited in place.

**Counts:** 22 ambiguity-pins, 7 mismatch-revisions (the §2.8 rewrite contains several of each, itemized below).

### Mismatch revisions (PRD described behavior impl does not exhibit)

- **§2.8** — revise — mismatch — subtree scoping moved out of the pre-existence authorization phase: ClientUser scope is checked only after the target resource loads, so a missing resource answers `ERR_NOT_FOUND` even to an out-of-subtree ClientUser — `implementation/routes/batches.py:145-146` (404 before `check_client_user_scope`), pattern repeated in all scoped getters.
- **§2.8** — revise — mismatch — body-referenced ids no longer claimed to be validated before body well-formedness; they are validated where each workflow first needs them (before suspension in grant/batch/session/shelf creation, after state checks in page-log/qa-review/download paths) — `implementation/routes/clients.py:224-232` vs `implementation/routes/scan_sessions.py:115-119`, `implementation/routes/batches.py:413-417`.
- **§2.8** — revise — mismatch — "no unknown keys" blanket rule scoped to endpoints that declare a payload schema; bodyless action endpoints accept and ignore any JSON object body — `implementation/routes/batches.py:159` (`get_body()` with no `reject_unknown` on all transitions), `implementation/routes/boxes.py:226,236`.
- **§2.8** — revise — mismatch — temporal windows (`ERR_GRANT_EXPIRED`) moved before state/business checks: the download path checks grant expiry before document-`DELIVERED`, vault, and scope — `implementation/routes/grants.py:109-123`.
- **§2.8** — revise — mismatch — custody-flag vs segregation order: destruction-certificate recording checks the flag *before* segregation (exception noted); the general order holds for the custody-events endpoint — `implementation/routes/boxes.py:263-265` vs `implementation/routes/boxes.py:189-190`.
- **§3.1** — revise — mismatch — suspension no longer blocks "every mutation on its subtree": agreement creation, manual shelf-assignment release, and custody-flag clearing carry no suspension check in impl and are now carved out — `implementation/routes/clients.py:112-163`, `implementation/routes/boxes.py:222-229,401-420`.
- **§4 intro** — revise — mismatch — "actions that modify return 200" gains one exception: `POST /batches/{id}/qa-reviews` returns **201** carrying the updated document — `implementation/routes/batches.py:431`.

### Ambiguity pins (PRD silent; pinned to impl)

- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` fall back to defaults; out-of-range values are clamped (limit→[1,100], offset→≥0), not rejected — `implementation/response.py:75-91`.
- **§2.3** — insert — ambiguity — `has_more` defined: true exactly when `offset + len(returned) < total_count` — `implementation/response.py:44`.
- **§2.3** — insert — ambiguity — additional exact-match `status` filters accepted on client batches/grants/invoices, batch boxes/scan-sessions, box documents, box/slot shelf-assignments — e.g. `implementation/routes/clients.py:193-196`, `implementation/routes/batches.py:296-299`, `implementation/routes/boxes.py:379-382`.
- **§2.4** — insert — ambiguity — `version` starts at 1 at creation — `implementation/util.py:34`.
- **§2.8** — insert — ambiguity — `ERR_STALE_VERSION` placed after state-machine legality, before business checks — `implementation/routes/scan_sessions.py:184-190`.
- **§2.8** — insert — ambiguity — `ERR_EMPTY_SCAN_SESSION` and `ERR_SCANNER_UNAVAILABLE` added to the ceilings list (commit order: empty → over-capacity → unavailable; open order: unavailable → busy); `ERR_BOX_RETURN_COMMITTED`/`ERR_BOX_NOT_RETURN_COMMITTED` added to business-safety after custody flag; string fields must be non-empty — `implementation/routes/scan_sessions.py:191-201,75-80`, `implementation/routes/boxes.py:240-242,315-316`, `implementation/util.py:94-97`.
- **§2.9** — insert — ambiguity — unknown paths and unsupported methods on known paths answer `ERR_NOT_FOUND` (404) — `implementation/app.py:39-45`.
- **§3.1** — insert — ambiguity — suspend only from `ACTIVE`, reactivate only from `SUSPENDED`, else `ERR_INVALID_STATE` (409) — `implementation/routes/clients.py:94-95,105-106`.
- **§3.1** — insert — ambiguity — agreement field ranges (`rush_multiplier` any number; free-days/rate/retention ≥0; `max_boxes_per_batch` ≥1) and no-agreement fallbacks (no box ceiling, subtotal recompute skipped, projected fee 0, retention treated as 0) — `implementation/routes/clients.py:139-146`, `implementation/routes/batches.py:257-267`, `implementation/services/serializers.py:106-110`.
- **§3.2** — insert — ambiguity — duplicate `box_label` within a batch → `ERR_INVALID_REQUEST` (400) — `implementation/routes/boxes.py:96-98`.
- **§3.2** — insert — ambiguity — duplicate `shelf_code` → `ERR_INVALID_STATE` (409); `capacity_grams` ≥1; manual release only from `ACTIVE` (else `ERR_INVALID_STATE`); occupied weight floored at zero on release — `implementation/routes/clock.py:130-133`, `implementation/routes/boxes.py:408-419`.
- **§3.3** — insert — ambiguity — `to_stage`↔role pairing enforced as `ERR_FORBIDDEN` (403) between the suspension and box-state checks; invalid `to_stage` → `ERR_INVALID_REQUEST`; recorded `from_stage` derived server-side (PREP←STORAGE, SCAN←PREP, STORAGE←SCAN) — `implementation/routes/boxes.py:161-195`.
- **§3.3** — insert — ambiguity — system custody links' stage pairs pinned: auto-intake `INTAKE→INTAKE`, shelving `INTAKE→STORAGE`, begin-destruction `STORAGE→DESTRUCTION`, mark-returned `STORAGE→RETURN` — `implementation/routes/boxes.py:117,245,319,369`.
- **§3.3** — insert — ambiguity — duplicate `scanner_code` → `ERR_INVALID_STATE` (409); `capacity_pages_per_session` ≥1; maintenance flips are unconditional even with an `OPEN` session — `implementation/routes/clock.py:55-58,89-103`.
- **§3.5** — insert — ambiguity — non-object `metadata_json` → `ERR_METADATA_INCOMPLETE` (422), same as a missing key — `implementation/routes/documents.py:71-72`.
- **§3.6** — insert — ambiguity — `delivery_status` is `PENDING` from batch creation until delivery — `implementation/routes/batches.py:101`.
- **§3.6** — insert — ambiguity — DRAFT-invoice read recomputation persists the refreshed subtotals, bumping `updated_at`/`version` when they change — `implementation/routes/invoices.py:36-53`.
- **§3.7** — insert — ambiguity — `certificate_code` format: `CERT-` + 16 uppercase hex characters — `implementation/routes/boxes.py:280`.
- **§3.8** — insert — ambiguity — expiry is strict (`expires_at` == clock still active), lazy expiry fires on any access including plain GET; using a `REVOKED` grant → `ERR_INVALID_STATE`; revoking a non-`ACTIVE` grant → `ERR_INVALID_STATE` — `implementation/routes/grants.py:43-56,70,81-83`.
- **§3.8** — insert — ambiguity — metadata channel lists every document of the batch regardless of status (including `REJECTED`) — `implementation/routes/grants.py:97`.
- **§3.8** — insert — ambiguity — download guard evaluation order pinned (suspension → doc existence → grant expiry/ACTIVE → doc `DELIVERED` → `vault_only` → scope); `expires_in_seconds` fixed at 300 — `implementation/routes/grants.py:106-128`.

Behaviors verified as already pinned (no change needed): rush admission boundary (count < 3), OCR fork at 70 with 200-on-reject, rejection allowance `max(1, floor(n/10))`, both page-ledger rules, OCC semantics, sweep inclusivity (`now >= disposition_at`), rounding-half-up per document, storage-day floor arithmetic, custody adjacency with insertion-order tiebreak, vault-zone rule, and the full RBAC table.
