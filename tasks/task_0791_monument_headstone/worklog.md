# Worklog — task_0791_monument_headstone

## Step 1: Create task directory — 2026-07-07T18:15:00.000Z

Used pre-assigned folder tasks/task_0791_monument_headstone as-is (Step 1 scan skipped per instructions). Created workspace/ subdirectory.

## Step 2: Generate scaffold (Expert) — 2026-07-07T18:46:00.000Z

All three artifacts are generated, parse cleanly (yaml.safe_load OK on all 3), pass `scaffold_lint.py` with a clean verdict, and every design-file `grounds` ref resolves.

## Generated: `task_0791_monument_headstone` (Expert)

**Files written** SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

**Scaffold shape**
- Archetype: workflow_orchestration + compliance_audit; topology flat; parallel/cyclic state shape; peer_roles; immediate consistency.
- **11 entities**: Cemetery, Customer, MonumentOrder, DesignProof, Payment, Workshop, FabricationJob, CemeteryPermit, InstallationCrew, Installation, RestorationJob (warranty modeled on the order + warranty-waived restorations rather than a separate entity).
- **32 endpoints** under `/memorials` (config creates, a logical-clock test endpoint defaulting to `2026-03-01T00:00:00Z`, order/proof/payment/fabrication/permit/installation/restoration CRUD + action transitions; every FK has reverse-reachability via sub-resource or filtered-list GET).
- **34 error codes**, **5 roles** (Admin opaque; Customer entity_backed:Customer; Designer, ShopManager, FieldOps opaque).
- **7 calculations** (dual-variant order pricing provisional↔final, per-line-rounded engraving charge, tiered material pricing, sum-then-round deposit split, dual-variant restoration quoted↔assessed, workshop/crew capacity aggregations, warranty window).

**State machines (7 declared)**
- MonumentOrder carries **parallel dimensions**: production_status (DRAFTING→IN_FABRICATION→READY_TO_INSTALL→INSTALLED, +CANCELLED) × payment_status (UNPAID→DEPOSIT_PAID→PAID_IN_FULL, +REFUNDED).
- DesignProof is **cyclic** (SUBMITTED→CHANGES_REQUESTED→SUBMITTED, revision_round++).
- FabricationJob, CemeteryPermit, Installation, RestorationJob lifecycles.
- One concurrency rule: OCC on `MonumentOrder.version` guarding design-proof creation (`expected_order_version`, ERR_STALE_ORDER_VERSION/412).

Note: removed an AWAITING_FABRICATION intermediate state during authoring so the cross-entity dependency (fabrication gated on an APPROVED proof) is actually reachable — approval sets the proof APPROVED and recomputes final price without advancing production.

**Difficulty design (§1.8)**: 18 instances — exactly 2 per each of the 9 Rules, all asserts pinned to code-computed literals (per-line engraving 11051 vs sum-then-round 11050; provisional merch 27700 vs final 30251; deposit 33880; warranty_expires_at 2036-03-25T12:00:00Z).

**Corner design (§1.9)**: 40 instances — 32 active recipes plus 8 `excluded_because` stubs.

**Lint**: `VERDICT: clean lint` — 32 endpoints, 11 entities, 18 §1.8 + 32 active §1.9 instances, 284 calls scanned, all conforming; all FKs reverse-reachable; no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-07-07T18:48:00.000Z

Copied INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T18:54:00.000Z

PRD generated at workspace/PRD.md (257 lines).

Sections: §1 Introduction; §2 Global Specs (11 subsections: RBAC, response envelope, pagination, common props/versioning with Payment as common_fields:false exception, monetary/dimensional precision, cemetery-spec compliance, capacity/scheduling/slot conflicts, OCC on proof creation, cascading consistency, validation ordering + nested retrieval, logical clock); §3 Business Logic (8 subsections); §4 endpoint table (32 endpoints); §5 error table.

Endpoints documented: 32 (matches scaffold). Notable calcs: per-line engraving 15% volume discount w/ per-line rounding-before-sum; tiered material pricing (3000/6000 cm² tiers, 100/110/125% mult, rates 8/15/11); contract assembly (45000-cent foundation flat + conditional permit fee, 40% deposit rounded once, balance = exact remainder); restoration quoted vs assessed (SEVERE +5000-cent surcharge, in-window warranty waiver inclusive boundary); warranty_window 120/60 months; capacity sums; signed payment ledger.

State machines: MonumentOrder parallel axes (production_status + payment_status), DesignProof cyclic revision loop (revision_round++, SUPERSEDED/VOIDED terminals), FabricationJob, CemeteryPermit, Installation, RestorationJob; depth-4 cancel cascade w/ capacity release + refund branch; OCC stale-version (expected_order_version → ERR_STALE_ORDER_VERSION 412).

Hard-contract results: Contract 1 Field-Name Coverage 58/58 PASS; Contract 3 §3 Path Purity 285 tokens, 0 leaks PASS; Contract 2 Rule Coverage PASS.

## Step 5: Generate unit tests — 2026-07-07T19:20:00.000Z

Test files: 9 (test_01–test_09) + conftest.py. 67 test functions, all collect under pytest, all compile, zero scaffold leakage, zero skip/xfail, every docstring carries exactly one Design: tag, all 72 quoted PRD citations verify verbatim.

Coverage: Queue A (§1.8) all 18 instances × 2 tests = 36. Queue B (§1.9) 31 of 32 non-stub instances (1 test each); 8 excluded_because stubs correctly not translated.

Skipped: 1 — Corner/state_machines/approve_superseded_proof_returns_not_current (not uniquely derivable: PRD §2.10 lumps ERR_PROOF_NOT_CURRENT + ERR_PROOF_NOT_SUBMITTED into 409 family with no ordering).

Design-adherence note: 4 difficulty instances assert Workshop/InstallationCrew.booked_minutes but no GET /workshops|/crews endpoint; second test of each asserts the conserved quantity via observable defining set (sum duration_minutes over SCHEDULED/ASSESSED jobs, PRD §2.7) or complementary boundary-accept.

test_helpers files (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. Payment TypedDict/assertion omit updated_at/version (append-only §2.4); Customer is only entity_backed role.

## Step 6: Generate implementation — 2026-07-07T19:20:00.000Z

Files: app.py (single-file server), requirements.txt (flask==3.0.3), start.sh. 32 endpoints implemented (matches PRD §4). start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guards pip install behind import check. In-memory module-level dicts, no seeding.

Verified by smoke: exact envelope + req_ ids + ms timestamps; per-line round-half-up engraving ([21,31] HUMAN → 11051; merch 71051, contract 126051, deposit 50420, balance 75631); tiered material mult; provisional vs final pricing; parallel production/payment axes; full lifecycle w/ version increments; logical clock default 2026-03-01, warranty window HUMAN 120mo → 2036-03-01, inclusive in-window waiver → assessed 0; OCC expected_order_version → ERR_STALE_ORDER_VERSION 412; depth-4 cancel cascade (fab CANCELLED, install CANCELLED, permit REVOKED, proofs VOIDED, capacity release, REFUND payment, payment_status REFUNDED); workshop half-open overlap, crew 60-min buffer; validation precedence per §2.10.

Spec gap noted: no dedicated error code for "installation on non-READY_TO_INSTALL order"; guard reuses nearest 409 (ERR_INSTALL_BEFORE_FAB_READY).

Verification: 67 tests collect cleanly (pytest --collect-only).

## Step 7: Run tests and iterate — 2026-07-07T19:26:00.000Z

The task was already in a fully passing state — no fixes needed.
- Iterations run: 1 (initial 8-round stability sweep passed clean, loop exited immediately).
- Result: all 8 rounds passed 67/67 (0 failed, 0 errors, 0 skipped). Ran as two waves of four per host-saturation guard; no boot-timeout errors in any round.
- Tests deleted: None.
- Fixes applied to test_helpers/: None.
- Fixes applied to implementation/: None.

Orchestrator re-ran the full 8-round sweep (2 waves of 4) to persist passing evidence: results.1–8.json all passed=67 total=67 failed=0 errors=0.

## Step 8: Finalize PRD — SKIPPED — 2026-07-07T19:26:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced. Step 9 runs from PRD.md.

## Step 9: Complete PRD — 2026-07-07T19:33:00.000Z

Produced workspace/PRD_COMPLETED.md (source PRD.md; PRD_FINALIZED.md absent since Step 8 skipped).

File deltas: PRD.md 257 lines / 36,629 chars → PRD_COMPLETED.md 257 lines / 38,159 chars (+1,530 chars, 0 line delta — all in-paragraph inserts/revisions, no new sections).

Counts: 7 changes — 4 mismatch-revisions, 3 ambiguity-pins.
- §2.1 — revise — mismatch — added "creating an order" to customer-scoped writes; impl enforces ERR_NOT_RESOURCE_OWNER on order create (app.py:698).
- §3.2 — insert — mismatch — pinned order create requires X-User-ID == customer_id, ownership check after existence(404) + well-formedness for create path (app.py:680-698).
- §3.3 — revise — mismatch — prior current proof superseded only when DRAFT/SUBMITTED/CHANGES_REQUESTED; APPROVED current proof untouched (app.py:809-814).
- §3.3 — insert — ambiguity — approve endpoint returns DesignProof resource, not order (app.py:869-874).
- §3.4 — revise — mismatch — BALANCE payment reaches PAID_IN_FULL from DEPOSIT_PAID or directly from UNPAID when covering whole contract (app.py:930-931).
- §3.6 — revise — ambiguity — non-READY_TO_INSTALL/no-COMPLETED-fab install rejected with ERR_INSTALL_BEFORE_FAB_READY (app.py:1128-1129).
- §3.8 — insert — ambiguity — restoration request enforces no production-status precondition; INSTALLED gate applies only to warranty waiver at assessment (app.py:1202-1230).

Left unchanged (already pinned/matching): pricing formulas, warranty math, cancel cascade, workshop/crew conflict rules, live-derived booked_minutes/amount_paid_cents, §2.10 precedence, logical-clock usage.

## PIPELINE COMPLETE — 2026-07-07T19:33:00.000Z

All 9 steps done. Final: 67 tests, 8/8 rounds passing 67/67. Step 8 skipped (clean first sweep). Artifacts: SCAFFOLD*.yaml (3), worklog.md, test_helpers/ (9), test_suite/ (9 + conftest), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}.
