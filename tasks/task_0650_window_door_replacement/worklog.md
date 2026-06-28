# Worklog — task_0650_window_door_replacement

Scenario: 650. Window & Door Replacement (Renewal by Andersen style): in-home consultation & measure, product/style configuration & energy rating, quote & financing/rebate (25C), custom manufacture & lead time, install crew & scheduling, permit & inspection, callback/service & warranty, referral

Difficulty: Expert

## Step 1: Create Task Directory — pre-created, scan skipped

Task directory `tasks/task_0650_window_door_replacement/` was pre-assigned and pre-created (with `workspace/`). Per execution constraints the index scan was skipped to avoid ID collision with parallel runs.

## Step 2: Generate Scaffold — 2026-06-26T10:09:00.000Z

All three scaffold artifacts are generated and pass the linter cleanly.

Generated the Expert-level scaffold for **task_0650_window_door_replacement** (Renewal by Andersen-style window/door replacement) from the scenario plus the skill spec only — no sibling tasks consulted. Three files written.

**Complexity profile:** `workflow_orchestration` × `pricing_engine`; layers = dual-variant calc, cascading side effects, optimistic concurrency, scheduled actions; topology `hybrid`; state-machine shape `branching`; role model `peer_roles`; `immediate` consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities (12):** Homeowner, Project (compound aggregate root), Consultation, Opening, Quote, FinancingApplication, ManufactureOrder, Crew, InstallJob, Permit, ServiceTicket, Referral (self-referential project↔project).
- **State machines (9):** Consultation, Quote (branching + cyclic REJECTED→DRAFT revision + auto-EXPIRE/SUPERSEDE), FinancingApplication, ManufactureOrder, InstallJob, Permit (cyclic INSPECTION_FAILED→APPROVED re-inspection), ServiceTicket (cyclic RESOLVED→REOPENED→DISPATCHED), Referral, Project (compound, derived from child stages). One concurrency rule: OCC on `Quote.version` for accept (412).
- **Calculations (7):** opening_unit_price (tiered), quote_estimate_total (round-then-sum + tier discount, order pinned), rebate_25c (estimate vs final HIGH-agi-zeroed variants, window/door caps), lead_time_days (max-select + triple-glaze surcharge), financing_monthly_payment (0% ceil vs amortized round_half_up), service_charge (warranty window), referral_reward (2% capped). All literals pre-computed by code.
- **Validations (20, priority-ordered):** auth → existence → ownership → state → OCC → business (safety/temporal/constraint/fiscal/referential).
- **Endpoints (65):** full business surface + flat single-GET/filtered-list read surface for FK reverse-reachability + `/_clock/set_current_utc` (default `2026-04-01T00:00:00Z`).
- **Errors (22)**; **Roles (5):** Homeowner (entity_backed), SalesConsultant/OperationsCoordinator/ServiceTech/PlatformAdmin (opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, all grounded in §1.1–§1.7, full empty-DB `setup_api_calls` chains, OCC versions via `${var}`.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 10 sections, **38 active instances + 2 `excluded_because` stubs** (citing valid §1.8 instances) covering entities/state-machines/calculations/validations/endpoints/errors/RBAC/cross-cutting layers/consistency/FK-reverse.

**Lint:** `VERDICT: clean lint` — 65 endpoints, 12 entities, 18+38 instances, 559 calls scanned, 0 violations.

## Step 3: Copy Shared Files — 2026-06-26T10:10:23.824Z

Copied `./INSTRUCTION.md` → `tasks/task_0650_window_door_replacement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T10:15:35.473Z

Generated `workspace/PRD.md` — prose PRD for Window & Door Replacement domain. 290 lines.

**Structure:** §1 Introduction; §2 Global Specs (10 subsections: RBAC, response envelope, pagination, common props, compound consistency, nested-path validation, precision/rounding, OCC, logical clock, jurisdictions/energy); §3 Business Logic (11 scattered lifecycle subsections); §4 Endpoint table (68 endpoints); §5 Error catalogue (21 errors).

**Hard Contract reports:** Field coverage PASS (58/58); Rule coverage PASS (20 validations + 1 OCC + all state machines + 7 calculations + 21 errors + cascades + sibling-branch symmetry, 0 missing); Path purity PASS (408 backtick tokens scanned, 0 path/method leaks in §3). Withheld DIFFICULTY/CORNER design files were not opened.

## Step 5: Generate Unit Tests — 2026-06-26T10:29:46.628Z

Generated complete test infrastructure for task_0650.

**test_helpers/ (9 files):** `__init__.py`, `types.py` (12 entity TypedDicts), `api_client.py` (~60 endpoints), `api_errors.py` (21 errors), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared role headers + `make_homeowner_headers` for entity_backed Homeowner), `fixtures.py` (5-tier composite setup).

**test_suite/ (conftest + 4 files, 74 test functions):** test_01_pricing_and_credits (12), test_02_workflows_and_cascades (19), test_03_validations_and_guards (30), test_04_entities_and_listing (13).

**Coverage:** Queue A (Difficulty) all 18 instances translated (≥2 tests each, 9 rules × 2). Queue B (Corner) all 38 non-stub instances translated (≥1 each). The 2 `excluded_because:` stubs correctly NOT translated. 74 tests / 74 verbatim `Design:` tags resolving to real instances.

**Instances skipped/weakened:** No full skips. One assertion dropped under PRD-first filter: `rebate_25c_provisional_vs_final_high_agi_zeroed` asserts "final confirmed 25C credit on accept for HIGH-agi == 0" but PRD names no response field for a final/confirmed credit and never states HIGH→zero phase-out in rule-bearing prose (computed-field silence — not uniquely derivable). The two PRD-covered halves were kept and tested.

**Verification:** all 74 tests collect cleanly; every PRD citation confirmed verbatim; no skip/skipif/xfail; no scaffold/design-index references in emitted code.

## Step 6: Generate Implementation — 2026-06-26T10:29:46.628Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Files (12):** `start.sh` (foreground launcher: reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py` (66 routes + validation-priority ordering + 4-hop accept cascade), `clock.py` (logical clock default `2026-04-01T00:00:00Z`), `db.py` (in-memory dict store), `errors.py` (full catalog), `response.py` (exact envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `calculations.py` (all 7 calcs with Decimal/ROUND_HALF_UP), `services.py` (compound status derivation, lazy expiry, cascades, credit recompute), `serializers.py`, `validation.py`.

**Endpoints:** All 65 from §1.5 + catch-all 404 (66 Flask rules total).

**Verification:** Four end-to-end smoke suites pass (lifecycle, pricing/rebate/lead-time, OCC + ownership, expiry, financing amortization, all cascades, warranty in/out, reopen cycle, validation ordering, 25C caps + AGI-HIGH zeroing). Storage purely in-memory (fresh restart wipes 9 projects → 0, clock resets to `2026-04-01T00:00:00.000Z`). No seeding/file/SQLite/JSON/tmp persistence. start.sh executable, reads $PORT, binds 0.0.0.0, foreground via exec.

## Step 7: Run Tests and Iterate — 2026-06-26T10:36:31.980Z

All 8 parallel rounds pass cleanly (72/72 each, 0 failures, 0 errors). Verified on disk: results.{1..8}.json all show passed=72 total=72.

**Iterations run:** 2 (initial diagnostic sweep + post-fix verification sweep).

**Tests deleted (2):** Both removed under STEP 1b **ERROR PRECEDENCE SILENCE / non-unique-derivability** — PRD does not uniquely determine the asserted outcome.

1. `test_accept_expired_quote_with_current_version_returns_quote_expired` (`test_suite/test_03_validations_and_guards.py`) — scaffold rule `Corner/errors/accept_expired_quote_returns_quote_expired`. Asserted accepting a quote after advancing clock past `expires_at` yields `ERR_QUOTE_EXPIRED`. But PRD §148 mandates lazy expiry "whenever the logical clock is set" (quote already `EXPIRED` at accept), and PRD §192 places the state guard (`ERR_INVALID_STATE`) before the quote-not-expired guard (`ERR_QUOTE_EXPIRED`). Two divergent PRD-faithful readings: A → `ERR_INVALID_STATE` (lazy expiry + state-first), B → `ERR_QUOTE_EXPIRED` (dedicated expiry guard vs pre-expiry SENT state). Both consistent → DELETE.

2. `test_accept_expired_and_stale_returns_stale_version` (same file) — scaffold rule `Difficulty/priority_pair_validation_conflict/quote_accept_expired_beats_stale_version_temporal_vs_state`. Same root cause: lazy expiry (§148) → quote `EXPIRED` → state guard fires before OCC stale-version check (§192 precedence). Asserted `ERR_STALE_QUOTE_VERSION` only reachable under Reading B → DELETE.

Complement test `test_accept_stale_version_alone_returns_stale_version` (clock left before expiry, quote stays SENT, only version mismatch trips) was KEPT — faithful and passing; isolates OCC without expiry ambiguity.

**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None — reference impl's accept-quote ordering (`app.py:accept_quote`, lazy-expire then state-check-first) is a PRD-faithful reading of §148 + §192; no change warranted.

**Final state:** 72/72 tests pass in all 8 parallel rounds, deterministically (no flakiness).

→ Step 7 made 2 deletions and 0 fixes. Step 8 is NOT skipped (deletions reveal PRD non-unique-derivability sites to pin).

## Step 8: Finalize PRD — 2026-06-26T10:39:22.317Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch of PRD.md pinning the impl's quote-accept ordering choice that PRD left under-determined.

**Line counts:** PRD.md = 290; PRD_FINALIZED.md = 290 (net 0 structural delta; single revised paragraph at §3.4 line 144, ~0.3% touched).

**Changes (1 bullet):**
- **§3.4 (line 144)** — *revise* — Pinned that lazy quote-expiry runs at the start of `accept`, so a quote past `expires_at` is already `EXPIRED` and fails the `SENT`-state guard with `ERR_INVALID_STATE` (state-first per §192), independent of any version mismatch; the dedicated `ERR_QUOTE_EXPIRED` outcome is reserved for the residual still-`SENT`/no-usable-`expires_at` case — `implementation/app.py:514` (expire_quote_if_due), `:521-522` (state guard), `:524-525` (OCC), `:526-529` (ERR_QUOTE_EXPIRED only when expires is None).

**Pre-edit search log:** subject = error returned on accepting an expired-at-accept quote + lazy-expiry/guard-ordering interaction. Enumerated `accept_quote` (app.py:505-565), `services.expire_quote_if_due` (services.py:53-67), all `expire_*_quotes` call sites (clock-set, read, cancel, list, get, accept, reject, send), `send_quote`, `reject_quote`. Wording scoped `ERR_QUOTE_EXPIRED` to the residual no-`expires_at` branch (app.py:528) rather than a universal claim; cross-referenced §148/§192 rather than redefining; added "regardless of whether expected_quote_version also happens to mismatch" to pin the deleted stale+expired test's actual outcome. Both deleted Step 7 tests trace to this single PRD silence (Reading A pinned).

## Step 9: Complete PRD — 2026-06-26T10:44:42.488Z

Produced `workspace/PRD_COMPLETED.md` — minimal patch over PRD_FINALIZED.md via full PRD-vs-implementation scan, pinning every residual ambiguity/mismatch to what impl actually does. All edits in-paragraph; no new sections.

**Line counts:** PRD_FINALIZED.md 290 → PRD_COMPLETED.md 290 (char-delta +5,239: 47,108 → 52,347).
**Counts:** 9 ambiguity-pins, 4 mismatch-revisions; 13 paragraphs touched.

**Per-change log:**
- §2.2 insert (ambiguity) — `api_request_timestamp` uses logical clock; `api_request_id` = `req_` + 20 random alphanumerics — response.py:11-22
- §2.3 insert (ambiguity) — non-integer limit/offset → `ERR_VALIDATION_LIMIT`; sort ties broken by ascending id; `has_more` = offset+limit < total_count — validation.py:21-49,56
- §2.5 insert (ambiguity) — compound status = highest milestone over current child states (full ladder); may regress; CANCELLED sticky; recompute bumps version only on change — services.py:95-144
- §2.5 revise (mismatch) — recompute advances version only when status value changes — services.py:130-144
- §2.10 revise (ambiguity) — jurisdiction from first character; empty/non-digit leading char → CENTRAL_LIGHT — app.py:179-185
- §3.1 revise (mismatch) — agi_band observably governs only financing APR; no binding energy-credit figure (final rebate path never invoked); explicit-null → STANDARD; invalid band → ERR_INVALID_REQUEST — app.py:145-149, calculations.py:125-130,497
- §3.1 insert (ambiguity) — duplicate homeowner email → ERR_INVALID_REQUEST — app.py:151-153
- §3.3 draft insert (mismatch) — drafting a quote does not require MEASURED consultation (only sending does); consultation must belong to project — app.py:432-437,489-491
- §3.3 supersede insert (mismatch) — supersede_quote_id need only exist on same project (not REJECTED, never modified); else ERR_REFERENCE_NOT_FOUND — app.py:438-442
- §3.4 insert (ambiguity) — missing/null expected_quote_version → ERR_INVALID_REQUEST (before state guard); non-integer → ERR_STALE_QUOTE_VERSION — app.py:517-525
- §3.6 revise (ambiguity) — start-build / mark-ready state + ready_at guards each reject with ERR_INVALID_STATE — app.py:688-689,702-706
- §3.7 scheduling insert (ambiguity) — scheduling not gated on project status; opening_count is 0 when no accepted_quote_id — app.py:808-814
- §3.7 depart revise (mismatch) — any READY manufacture order on project satisfies goods-ready; not-SCHEDULED and before-window_start each → ERR_INVALID_STATE; guard order pinned — app.py:882-891
- §3.9 insert (mismatch) — opening must exist first (ERR_REFERENCE_NOT_FOUND); project-COMPLETED check precedes opening-belongs; foreign-project opening → ERR_PROJECT_NOT_COMPLETED — app.py:1016-1025
- §3.10 insert (ambiguity) — referral created when referred project already CONTRACTED settles immediately at creation (returned SETTLED) — app.py:1148-1149
- §3.11 insert (mismatch) — mandatory action-field validation (decision/result/expected_quote_version) for transition endpoints fires before state guard (exception to "last of all" governing create endpoints) — app.py:638-641,984-987,517-521

---

## PIPELINE COMPLETE

All 9 steps finished. Final state: 72/72 tests pass across all 8 parallel stability rounds. `PRD_COMPLETED.md` exists on disk. Pipeline terminated successfully.
