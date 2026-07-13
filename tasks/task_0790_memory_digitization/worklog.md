# Worklog — task_0790_memory_digitization

## Step 1: Create Task Directory — 2026-07-07T10:59:37.000Z

Task directory pre-assigned: tasks/task_0790_memory_digitization with workspace/ subdirectory. Step 1 index scan skipped per run instructions (folder pre-assigned to avoid ID contention with parallel runs). Verified directory and empty workspace/ exist.

## Step 2: Generate Scaffold (Expert) — 2026-07-07T11:40:00.000Z

All three scaffold artifacts are complete, parse cleanly, and pass `scaffold_lint.py` (`VERDICT: clean lint`). Verified all three safe_load cleanly.

Generated the full scaffold for **task_0790_memory_digitization** (Expert) purely from the scenario + skill spec, without consulting any sibling task.

**Domain modeling** — Legacybox-style media digitization framed as a *workflow-orchestration + pricing-engine* archetype, `flat` topology, `parallel` state-machine shape, `peer_roles`, immediate consistency. Layers: dual-variant calc, cascading side effects, optimistic concurrency, rate/threshold triggers.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities**: Customer, Order, Machine, StorageBin, Batch, MediaItem, QCReview, OutputArtifact, DownloadEvent, DamageClaim (all FKs use canonical `FK -> X.id` prefix; every FK has a reverse-reachability GET).
- **32 endpoints** (incl. `/_clock/set_current_utc` with the mandated 2026-03-01 default).
- **5 state machines**: Order (parallel payment × fulfillment axes), MediaItem (cyclic QC revision loop), Batch, DamageClaim (branching), OutputArtifact.
- **4 calculations**: `order_subtotal` (tiered, dual-variant estimate/final), `order_total` (pinned evaluation order for promo band = mode-c), `customer_risk_score` (weighted, provisional/settled), `damage_payout` (threshold/cap).
- **1 concurrency rule**: OCC on `Order.version` for output-artifact generation (ERR_STALE_ORDER_VERSION, 412).
- **19 error codes** (all referenced ≥2×; no forbidden concurrency vocabulary), **20 validations**, **5 roles**.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 rules × 2 = 18 instances**, each differentiated across entity domains / error-category pairs / conserved quantities, with executable `setup_api_calls` chains and formula-derived asserts pre-computed as literals (estimate 2400 vs final 1200, volume boundary 21600 vs 22800, mode-c promo 12740, payouts 1000/4000/10000).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **7 sections, 21 active instances + 4 excluded_because stubs** — creation/defaults/required-field/enum/not-found/FK, invalid-transition & QC-attempt boundary, calc correctness, RBAC denials + ownership, missing-auth, OCC stale-version, and dedicated tests for every otherwise-uncovered error (including ERR_NOT_DOWNLOADABLE and ERR_DOWNLOAD_EXPIRED).

**Lint:** clean — 347 calls scanned across §1.8+§1.9, all conform to §1.5, all FKs reverse-reachable.

Two minor mechanical fixes applied during generation: quoting bare-`?` flow-list items and nested-`[` grounds items so all three files `yaml.safe_load` cleanly; and reshaping the QC-FAIL transition so ERR_QC_ATTEMPTS_EXCEEDED is reachable.

## Step 3: Copy Shared Files — 2026-07-07T11:40:11.000Z

Copied ./INSTRUCTION.md → tasks/task_0790_memory_digitization/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T11:46:25.000Z

Generated workspace/PRD.md (272 lines). Endpoints documented: 32; error codes: 19.

Sections covered: §1 Introduction; §2 Global Specs (RBAC 5 roles/header identity translation, fixed response envelope, pagination, common props + versioning, monetary precision round-half-up, logical clock 2026-03-01 default, OCC on deliverable generation, nested retrieval + FK existence, validation ordering/precedence); §3 Business Logic (7 subsections: order placement + estimate pricing, payment authorize/capture parallel axes, intake + bin retention, batching + cross-entity scan gate, QC + rescan loop 3-attempt cap, ready + deliverable generation + downloads expiry/limit/lazy EXPIRED, damage claims + depth-3 refund cascade + payout policy + final recompute); §4 endpoint table; §5 error table.

Hard-contract verification (programmatic): Field-Name Coverage 63/63 required identifiers, 0 missing; Rule Coverage all 4 calculations as precise prose, OCC rule complete, all transitions/preconditions/cascades expressed, validation priority stated, all 19 error IDs in prose; §3 Path Purity 0 paths / 0 bare HTTP methods across 300 tokens; all 22 enum + 28 state values verbatim. Confirmed neither withheld design file was read.

## Step 5: Generate Unit Tests — 2026-07-07T12:05:13.000Z

Test files: 8 (conftest.py + 7 test_*.py). Test functions: 55 total (Queue A/Difficulty: 34 = 17 instances × 2; Queue B/Corner: 21 = 21 non-stub instances × 1). Every test docstring carries a verbatim PRD citation + one Design: tag resolving to a real instance.

Instances skipped (1, unique-derivability failure): Difficulty/dual_variant_calc/customer_risk_provisional_vs_settled_diverge — design asserts persisted risk_score==20 (settled/approved-only) but PRD §3.7 defines risk_score as 20×APPROVED + 5×SUBMITTED "as they stand", so a faithful PRD-only reader with approved=1,pending=1 computes 25. Not uniquely derivable → skipped rather than weakened. That difficulty instance has 0 tests (reported gap).

Corner stubs correctly not translated (4): machine_double_book_corner, mediaitem_qc_cycle_corner, estimate_vs_final_corner, output_not_ready_corner (each excluded_because → a real difficulty instance owning the assertion).

test_helpers files (9): __init__.py, types.py (QCReview/DownloadEvent omit updated_at/version per common_fields:false), api_client.py (34 endpoint methods), api_errors.py (19 errors + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque role constants + make_customer_headers), fixtures.py (composite state-progression helpers). Full suite collects cleanly (55 tests, 0 import errors — verified from task root).

## Step 6: Generate Implementation — 2026-07-07T12:05:13.000Z

Files: app.py (~1050 lines single-file Flask), requirements.txt (Flask==3.0.3), start.sh (guarded dep install + exec python3 app.py). Endpoints wired: 32 routes.

State machines: Order parallel axes (fulfillment QUOTED→AWAITING_MEDIA→RECEIVED→PROCESSING→READY; payment UNPAID→AUTHORIZED→CAPTURED→PARTIALLY_REFUNDED; READY bubble-up re-eval); MediaItem cyclic QC_FAIL→SCANNING rescan loop capped MAX_QC_ATTEMPTS=3 (ERR_QC_ATTEMPTS_EXCEEDED); Batch OPEN→LOADED→RUNNING→COMPLETED (cross-entity gate ERR_ORDER_NOT_RECEIVED); DamageClaim branching + depth-3 approval cascade; OutputArtifact supersede-on-regenerate + lazy EXPIRED on download.

Calculations (integer cents, Decimal ROUND_HALF_UP): order_subtotal (per-type rates + volume tiers 10%/20%), order_total (rush 30%, protection 1500+2%, SAVE5 promo bands), estimate vs final variants; damage_payout (protection vs limited-liability caps); customer_risk_score (20×approved + 5×pending, cap 100).

Details: logical clock default 2026-03-01T00:00:00Z; half-open bin-overlap sweep-line (ERR_BIN_CAPACITY_EXCEEDED); machine double-booking (ERR_MACHINE_DOUBLE_BOOKED, adjacency allowed); OCC expected_order_version (ERR_STALE_ORDER_VERSION 412); validation precedence ladder per §2.9; exact response envelope; in-memory dicts only, no seeding. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec.

## Step 7: Run Tests and Iterate — 2026-07-07T12:08:36.000Z

All 8 rounds clean: 55/55 passed, 0 failed, 0 errors, 0 skipped in every round (independently verified by orchestrator reading results.1-8.json — status key is `status`).

- Iterations run: 1 (single 8-round sweep, two waves of four to avoid host self-saturation).
- Tests deleted: 0.
- Fixes applied to test_suite/: 0.
- Fixes applied to test_helpers/: 0.
- Fixes applied to implementation/: 0.
- Exited on the FIRST sweep with 0 deletions / 0 fixes (0 iterations beyond baseline). Task was already clean.

## Step 8: Finalize PRD — 2026-07-07T12:08:36.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes. PRD.md already determined every behavior the implementation exhibits at the tested sites. PRD_FINALIZED.md is not produced; Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-07-07T12:13:28.000Z

Produced workspace/PRD_COMPLETED.md from PRD.md via full PRD-vs-implementation scan. Source PRD.md 271 lines / 35,415 chars → PRD_COMPLETED.md 271 lines / 37,484 chars (Δ +2,069 chars, all in-paragraph, no new lines/sections). Counts: 8 ambiguity-pins, 1 mismatch-revision.

Changes:
- §2.1 (RBAC) — insert — ambiguity — Customer may name only own customer_id on order create (else ERR_NOT_OWNER); may read only own Customer record — app.py:671, 686.
- §2.2 (Response Structure) — insert — ambiguity — api_request_timestamp read from logical clock, not wall time — app.py:144.
- §2.3 (Pagination) — insert — ambiguity — optional per-endpoint equality filters (/orders, /media-items, /batches) + implicit Customer-owner scoping on GET /orders — app.py:748-758.
- §3.1 (Order creation) — revise — mismatch — gift_recipient_email never required, stored as supplied, not enforced when is_gift true nor cleared when false — app.py:696, 716.
- §3.3 (Intake) — insert — ambiguity — duplicate barcode rejected ERR_VALIDATION (400) — app.py:825-827.
- §3.5 (Scan completion) — insert — ambiguity — digitized_minutes & page_count both optional; digitized_minutes any number, page_count integer — app.py:1000-1009.
- §4 (Endpoint intro) — insert — ambiguity — qc-review & download return 201 Created; qc-review data = updated media item, download data = new DownloadEvent — app.py:1046, 1151.
- §3.7 (Claims) — insert — ambiguity — 90-day claim window enforced only after order reaches READY — app.py:1185.
- §3.7 (Customer fields) — insert — ambiguity — email/full_name/state_code non-empty strings; missing/empty/duplicate email → ERR_VALIDATION (400) — app.py:653-658.

Pipeline complete. Final state: 55/55 tests pass across all 8 stability rounds.
