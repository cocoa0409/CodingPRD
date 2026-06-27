# Worklog — task_0506_equity_crowdfunding_regcf

## Step 1: Create task directory — 2026-06-26T08:22:33.000Z

Created `tasks/task_0506_equity_crowdfunding_regcf/` and `tasks/task_0506_equity_crowdfunding_regcf/workspace/` (pre-allocated reserved index 0506; did not scan ./tasks).

## Step 2: Generate scaffold (Expert tier) — 2026-06-26T08:43:13.000Z

All three required files present; scaffold lint passes clean (SCAFFOLD.yaml 1480 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1322 lines, SCAFFOLD_CORNER_DESIGN.yaml 1654 lines).

Generated an **Expert-tier** scaffold for **task_0506_equity_crowdfunding_regcf** (Reg CF equity crowdfunding portal). All three files written and `scaffold_lint.py` returns **VERDICT: clean lint** (476 calls scanned, all conform to §1.5; all FKs reverse-reachable).

**Complexity profile**: primary archetype `compliance_audit` + secondary `quota_allocation`; flat topology; branching state-machine shape; `segregation_of_duties` role model; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7)**:
- **8 entities**: Issuer, Offering (with parallel `form_c_status` × `status` dimensions), Investor, AccreditationRequest, Investment, EscrowAccount, CapTableEntry (`common_fields: false`, immutable), InvestorUpdate (self-referential `supersedes_update_id`).
- **6 state machines**: Issuer (linear+bar), Offering primary (branching LIVE→{FUNDED,FAILED}, FUNDED self-loop secondary, rolling-close LIVE→LIVE), Offering.form_c (cyclic REJECTED↔SUBMITTED + amend loop), AccreditationRequest, Investment (5 states with system sweep/refund), InvestorUpdate (supersede cascade).
- **10 calculations**: Reg CF investor_annual_limit (dual-branch), trailing_12mo_committed (aggregation w/ accredited bypass), offering_committed/swept, escrow_held (conservation invariant), equity_issuance (EQUITY shares+remainder vs SAFE principal), close_disbursement (fee-on-sum, round_half_up), issuer_trailing_12mo_proceeds ($5M cap), offering_campaign_overlap (closed-interval), update_quiet_period (point-with-buffer).
- **21 validations** (priority-ordered, incl. 9.1/9.2 temporal), **38 endpoints** (incl. `/_clock/set_current_utc` default `2026-01-01T00:00:00Z`, all FK reverse-reachability GETs), **21 errors**, **4 roles** (Anonymous, Issuer/Investor entity-backed, ComplianceOfficer opaque), **1 concurrency rule** (`commit-against-stale-offering`, OCC on Offering.version → 412).

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml**: **18 instances** — exactly 2 per all 9 Difficulty Rules, each with literal-pinned asserts (computed in code: e.g. 232 shares + 600c remainder; fee-on-sum 15001 vs per-line 15000; net disbursed 185006c; rolling-close disbursed 2312500c; annual-limit 250000/2000000/500000c; campaign-overlap and 24h-strict-gap datetime boundaries).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml**: **33 active corner instances + 5 excluded_because stubs** spanning all 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting layers incl. OCC stale/happy paths + derived-field reconciliation, consistency_model). All stub `difficulty_instance` references resolve; no name collisions across files; all grounds resolve to §1.1–§1.7.

## Step 3: Copy shared files — 2026-06-26T08:43:39.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T08:49:10.000Z

**Output:** `workspace/PRD.md` (245 lines). All three Hard Contracts verified PASS.

**Domain:** Equity Crowdfunding (Reg CF / Reg A+) portal — issuer onboarding & Form C, offerings with min/max targets, accreditation & annual-limit checks, escrow funding, rolling/final closes with share issuance to a cap table, auto-refund on failed raise, secondary listing, and investor updates.

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC + identity translation, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning (CapTableEntry common_fields:false), 2.5 Nested Retrieval, 2.6 Integer-Cent Precision, 2.7 OCC, 2.8 Validation Ordering, 2.9 Logical Clock boots 2026-01-01T00:00:00Z); §3 Business Logic (8 subsections, lifecycle grouping); §4 Endpoint table (37 endpoints); §5 Error table (21 errors).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) 49/49 PASS; Contract 2 (Rule Coverage) all 33 enum/state values, 21 error IDs, 7 calc constant sets, OCC, annual-limit dual variant, issuance/disbursement waterfalls, refund cascades, secondary-listing gating, commit-cascade priority ordering all PASS; Contract 3 (§3 Path Purity) 347 tokens, 0 violations PASS.

**Notable coverage decisions:** create-investment business-check cascade rendered as explicit ordered list in §3.4 (deadline → OCC → annual-limit → per-investor-cap → oversubscription); expected_offering_version introduced §2.7 reused §3.4; supersedes_update_id in §3.8 + §4 filter sentence; §2.2 emitted byte-for-byte from canonical source.

## Step 5: Generate unit tests — 2026-06-26T09:02:14.000Z

Generated complete test infrastructure translating exclusively from the two design indices. 69 tests total, 69 Design tags (exactly one per test).

**Stage 1 — `test_helpers/` (9 files):** types.py (10 enums + entity TypedDicts; CapTableEntry carries only id/created_at), api_client.py (37 endpoints incl. /_clock/set_current_utc), api_errors.py (22 error IDs + HTTP status map), assertions.py, factories.py (unique EIN/email generators), constants.py, test_users.py (entity-backed make_*_headers builders), fixtures.py (tiered composite helpers).

**Stage 2 — `test_suite/` (conftest + 5 files, 69 tests):** test_01_onboarding_and_access (17), test_02_form_c_and_lifecycle (13), test_03_commitments_and_limits (18), test_04_closing_and_disbursement (14), test_05_temporal_and_updates (7).

**Coverage:** Queue A (Difficulty) all 18 instances translated, 2 tests each (36 tests), 0 skipped. Queue B (Corner) all 33 non-stub instances translated, ≥1 test each (33 tests), 0 skipped. 5 stub instances correctly NOT translated; all 5 difficulty_instance cross-refs resolve.

**Audits passed:** all files byte-compile; every test_suite import resolves; 69 functions/69 Design tags; no skip/skipif/xfail; every docstring citation survives whitespace-normalized grep of PRD.md.

**Notable adjudication:** two priority-pair conflict instances passed unique-derivability because PRD pins both orderings (§2.8 structural state-check before business rules = state_beats_fiscal; §3.4 orders annual-limit before oversubscription = safety_beats_fiscal). No instances required skipping.

## Step 6: Generate implementation — 2026-06-26T09:02:14.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**File structure:** start.sh (foreground; reads $PORT default 10000, binds 0.0.0.0, guards pip install on `import flask` check, then `exec python3 app.py`); app.py (factory, blueprints, error handlers); requirements.txt (flask==3.0.3); foundation modules clock.py (logical clock default 2026-01-01T00:00:00Z), errors.py, response.py (envelope), middleware.py (4-role auth via X-User-ID/X-User-Role), pagination.py (limit/offset/total_count/has_more, default 10, 1–100), validation.py, db.py (in-memory dicts + insertion seq + investor wallets), serializers.py, calculations.py, derive.py, offering_service.py (close-batch sweep + auto-refund cascade); routes/ (issuers, offerings, cap_table, investors, investments, investor_updates, clock_routes).

**Notable design choices:** in-memory only, empty on boot (no seeding); commit business checks run in PRD §3.4 order (not scaffold numeric priority); integer-cent math, single rounding (7.5% fee on batch sum via Decimal ROUND_HALF_UP); equity sub-share remainders refunded to wallet; CapTableEntry immutable (id/created_at only); final-close branching FUNDED/FAILED/ERR_MINIMUM_NOT_MET; closed-interval campaign-overlap strict < (touching allowed); quiet-period strict >24h with supersede exemption + PUBLISHED→SUPERSEDED cascade.

**Verification:** ran ~60 live assertions across four scenario scripts; all passed; all modules byte-compile; clean restart confirmed (fresh boot total_count:0).

## Step 7: Test and iterate to PASS — 2026-06-26T09:11:11.000Z

Final 8-round parallel sweep: all 8 rounds 69/69 (clean).

**Iterations run:** 3 full 8-round parallel sweeps.
- Sweep 1: 67/69 each round — 2 consistent failures.
- Sweep 2: 68–69/69 — 2 original failures fixed; 1 new flaky transport failure surfaced (round 1 only).
- Sweep 3: 69/69 all 8 rounds — clean.

**Tests deleted:** None.

**Fixes applied to test_suite/** (both STEP 2 test-bug fixes — rule is PRD-verbatim and uniquely derivable, so implementation was correct and test artifacts were wrong):
- `test_03_commitments_and_limits.py` → `test_issuer_cap_exceeded_on_offering_create`: fixture confused dollars with cents (prior raise 4,800,000c + max_target 300,001c, sum 5,100,001 < cap 500,000,000c per PRD §3.2 "five million dollars, i.e. 500,000,000 cents"), so PRD-faithful impl correctly created the offering. Scaled amounts to 480,000,000 + 30,000,001 = 510,000,001 > 500,000,000 (and raised investor income/net-worth so the larger commitment passes) so the cap genuinely trips with ERR_ISSUER_CAP_EXCEEDED.
- `test_04_closing_and_disbursement.py` → `test_commit_then_withdraw_conserves_escrow_held`: STEP 1c partial coverage. PRD §3.5 withdrawal sentence is silent on escrow's `refunded_amount_cents` (only bulk failed-raise/cancellation cascades advance it — BRANCH-ASYMMETRIC SIDE EFFECT). Removed uncovered assertion `escrow["refunded_amount_cents"] == 300_000`; kept covered assertions (status, refund_amount_cents, committed→0, held→0).

**Fixes applied to implementation/** (robustness, not behavior — no PRD-traced endpoint/field/side-effect added):
- `app.py` (`__main__`): switched WSGI server from Werkzeug dev server to **waitress** (`serve(app, host="0.0.0.0", port=port, threads=8)`) with ImportError fallback. Dev server intermittently dropped connections (BadStatusLine) under 8× concurrent-round load (sweep-2 round 1 only). Waitress removed the flakiness.
- `requirements.txt`: added `waitress==3.0.0`.
- `start.sh`: extended install-skip guard from `import flask` to `import flask, waitress`.

Storage remains in-memory only (Python dicts, empty on every boot); no seeding, no persistence.

## Step 8: Finalize PRD — 2026-06-26T09:14:27.000Z

**Output:** `workspace/PRD_FINALIZED.md` (245 lines, ~0% delta — one line revised in place, none added/removed).

**Changes (1):**
- §3.5 (Withdrawals) — *revise* — appended a clause stating a single-investment withdrawal does NOT advance the escrow account's `refunded_amount_cents` (only `held_amount_cents` changes), in contrast to the bulk failed-raise/cancellation cascades — `routes/investments.py:186-196` vs `offering_service.py:107`.

**Pre-edit search log:** subject = escrow `refunded_amount_cents`; enumerated all three write sites (offerings.py:261 init, offering_service.py:81 sweep_batch close, offering_service.py:107 refund_all_unswept); confirmed withdraw_investment (investments.py:170-197) writes only investment refund_amount_cents + wallet credit + recompute held_amount_cents. Wording scoped to single-investment withdrawal only, framed as contrast to bulk cascades, no universal claim.

**Items deliberately NOT edited:** test_03 issuer-cap fixture fix (pure fixture arithmetic; PRD §3.2/§3.7 already say "500,000,000 cents" verbatim, uniquely derivable); app.py waitress swap / requirements.txt / start.sh (infrastructure/robustness only, no behavioral PRD surface).

## Step 9: Complete PRD — 2026-06-26T09:23:01.000Z

**Output:** `workspace/PRD_COMPLETED.md` (245 lines, 42,787 chars; +2,453 chars over PRD_FINALIZED.md; all edits in-paragraph, no new sections — 22 headers unchanged).

**Counts:** 3 ambiguity-pins, 3 mismatch-revisions (6 changes across 5 paragraphs).

**Changes:**
- §3.7 — insert — ambiguity — `GET /offerings/{id}/escrow` is a paginated list (response_type array, full pagination meta) holding the single escrow as sole element (empty when none); missing escrow does not 404 — routes/offerings.py:368-376.
- §3.2 — revise — mismatch — segregation of duties applies to both qualify AND reject, runs BEFORE state check (self-review → ERR_SEGREGATION_OF_DUTIES even when not SUBMITTED); primary-status-must-be-DRAFT applies only to initial DRAFT→SUBMITTED not REJECTED→SUBMITTED — routes/offerings.py:165-191,149-159.
- §3.4 (per-investor cap) — insert — ambiguity — pinned cumulative basis: sum of amount_cents over investor's COMMITTED/RECONFIRMED/ISSUED investments on this offering (excl CANCELLED/REFUNDED) + new amount vs per_investor_cap_cents — routes/investments.py:84-95.
- §3.4 (commit payload) — revise — mismatch — amount_cents ≤ 0 rejected as body well-formedness with ERR_INVALID_REQUEST — routes/investments.py:47; validation.py:43-49.
- §3.4 (commit creation) — insert — ambiguity — supplied expected_offering_version persisted on investment record and echoed back as a field — routes/investments.py:109; serializers.py:8-9.
- §3.6 (close branching) — revise — mismatch — pinned final-close decision tree (state gate LIVE only; FUNDED requires QUALIFIED Form C; else swept+committed decides — below min→FAILED, at/above min but reconfirm-blocked→ERR_MINIMUM_NOT_MET staying LIVE) and rolling close checks LIVE+QUALIFIED before minimum, never FAILED — routes/offerings.py:296-333,276-293; offering_service.py:21-33.

---

## PIPELINE COMPLETE — 2026-06-26T09:23:01.000Z

All 9 steps complete. Final 8-round stability sweep: 69/69 tests passing across all 8 rounds. Task directory fully populated:
- SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml
- worklog.md
- test_helpers/ (9 files) + test_suite/ (conftest + 5 test files, 69 tests)
- workspace/: INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (+ results.1..8.json all passing)
