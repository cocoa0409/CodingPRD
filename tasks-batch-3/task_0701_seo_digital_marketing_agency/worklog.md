# Worklog — task_0701_seo_digital_marketing_agency

Scenario (verbatim): 701. SEO & Digital-Marketing Agency: client/site audit & keyword strategy, deliverable (content/backlink/technical) & sprint, rank/traffic tracking & reporting, retainer & scope/credits, PPC ad-spend management & markup, local-listing/GBP optimization, contract & renewal, white-label reseller

## Step 1: Create Task Directory — 2026-06-29T02:38:03.576Z

Task directory pre-created by orchestrator; ./tasks scan + index computation SKIPPED per invocation constraints. task_dir fixed to tasks/task_0701_seo_digital_marketing_agency (workspace/ subdirectory already exists). No other numbered directory created or used.

## Step 2: Generate Scaffold — 2026-06-29T02:57:30.268Z

All three files are in place and valid. The scaffold generation is complete.

## Summary

Generated the three-file Expert-tier scaffold for **task_0701_seo_digital_marketing_agency** (SEO & Digital-Marketing Agency). All files pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Difficulty tier:** Expert
**Entity count:** 13 (Reseller, Client, SiteAudit, KeywordTarget, RankSnapshot, Retainer, Contract, Sprint, Deliverable, AdCampaign, AdSpendDispute, GbpListing, Report)
**Endpoint count:** 74 raw (48 POST actions + 26 GET reads), including one `/_clock/set_current_utc` test-driving endpoint
**Validation count:** 21 (contiguous priorities 1–21)
**Calculation count:** 11 (with 3 carrying dual variants / multi-mode complexity)
**State-machine count:** 9 (incl. cyclic, parallel-dimension, and branching shapes)
**Error catalog:** 22 codes, every one referenced; **concurrency rules:** 2 OCC-on-`Retainer.version`

**Difficulty rules:** all 9 §0.5 rules satisfied with exactly 2 instances each (18 §1.8 instances); §1.9 carries 34 active corner instances + 12 `excluded_because` stubs (all stub refs resolve to named §1.8 instances; all names unique across both files).

**Notable design decisions:**
- **Archetype:** quota/allocation (retainer credit pool reserved→committed→consumed→released) blended with pricing-engine (tiered PPC markup, reseller billing markup).
- **Flat topology** with `api_prefix: /` — every resource is a top-level collection cross-linked by FK fields (required for the lint's collection-segment inference and FK reverse-reachability across 13 entities).
- **Dual-variant calcs on different domains:** live-estimate vs invoiced-final PPC fee (AdCampaign) and direct vs reseller-markup billing price (Retainer).
- **Two distinct temporal-overlap semantics (Rule 8):** Sprint windows are half-open `[start,end)` (adjacency allowed); Report periods are closed-with-1-day-buffer.
- **AdCampaign carries two parallel state dimensions** (lifecycle × billing) that evolve independently — drives Rule 3.
- **Depth-3 cascade** (Client churn → Retainer close → Deliverable cancel → credit release) and a second cascade from dispute-UPHELD (spend reduction → fee recompute + health recompute).
- **Two compensating invariants over different conserved quantities:** retainer credit pool (credits) and total recorded ad spend (cents = spent_cents + upheld credited_cents).
- **Endpoint count is above the nominal Expert 20–32 band** — driven by hard structural constraints (FK reverse-reachability GET per FK, computed-field retrieval that only surfaces on GET, and the action endpoints intrinsic to 9 state machines), not padding; difficulty lives in the credit-ledger coupling, tiered-fee rounding, and cross-entity cascades.
- Added empty-set handling for `rank_momentum`/`avg_rank`, removed a dead `Reseller.SUSPENDED` enum value, and verified all numeric asserts against executed formula code.

The hard constraint was honored: no sibling `task_*/` directory was read, globbed, or grepped — the scaffold was built purely from the scenario plus the skill specification, examples, and lint script.

## Step 3: Copy Shared Files — 2026-06-29T02:57:51.222Z

Copied ./INSTRUCTION.md → tasks/task_0701_seo_digital_marketing_agency/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-29T03:04:20.565Z

PRD generated at workspace/PRD.md.

**PRD line count:** 308 lines.

**Sections produced:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 11 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties/Versioning, 2.5 Hierarchical Consistency/Cascades, 2.6 Nested Retrieval/Referential Existence, 2.7 Validation Order, 2.8 OCC on Retainer Credit Pool, 2.9 Credit Ledger Principle, 2.10 Monetary Precision/Rounding, 2.11 Logical Clock
- §3 Business Logic — 9 subsections grouped by entity-lifecycle: Resellers/Clients/Onboarding, Keyword Strategy/Rank Tracking, Reporting/Momentum/Health, Retainers/Billing Cycle, Contracts/Renewal/Termination, Sprints/Deliverable Lifecycle, Ad Campaigns/Management Fee, Ad-Spend Disputes, Local Listings
- §4 Endpoint Definitions (4-column table, 73 endpoints)
- §5 Error Code Catalogue (2-column table, 22 errors)

**Coverage:** 13 entities; 73 endpoints; 9 state machines / 48 transitions (Client 6, Retainer 6, Contract 7, Sprint 2, Deliverable 10, AdCampaign 6 across dual lifecycle+billing dimensions, AdSpendDispute 4, GbpListing 4, KeywordTarget 3); 11 calculations; 2 OCC concurrency rules; 21 priority-ordered validations; 22 errors.

Field coverage check: PASS (66/66 fields, 42/42 request bodies, 10/10 query params, 1/1 path params).
Rule coverage check: PASS (21 validations, 2 OCC, 48 transitions, 11 calcs all expressed).
Path purity check (§3 only): PASS (0 path-like tokens of 561 scanned).

**Notable choices:**
- Added explicit §2.7 Validation Order subsection expressing the 21-rule priority chain.
- Surfaced PPC management fee marginal tiered markup with both variants (live UNBILLED estimate vs frozen invoiced_final) and pinned per-tier→sum→single-floor order, plus reseller-vs-agency base-rate fork.
- Embedded constants with unit conversions for inference difficulty.
- Both OCC sites framed purely in stale-version terms, no race/simultaneity language.
- Withheld SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-29T03:22:10.793Z

**Helper modules produced (9 files in `test_helpers/`):** types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py, __init__.py

**Test files: 8** (test_01–test_08) + conftest.py

**Total test functions: 70** — all collect cleanly under pytest.
- **Queue A (Difficulty): 36 tests** covering all 18 instances, each with ≥2 tests (9 rules × 2 instances). No broken tags.
- **Queue B (Corner): 34 tests** covering all 34 non-stub instances, exactly ≥1 each. All 12 excluded_because stubs correctly NOT translated.

**Instances skipped: 0.** Every queue-A and non-stub queue-B instance passed the PRD-first two-condition filter.

**One faithfulness adjustment (not a skip):** priority_pair_validation_conflict/assign_retainer_not_active_beats_insufficient_credits — PRD §2.7 does not pin precedence between two business rules, so its two tests use validate_error_is_one_of([ERR_RETAINER_NOT_ACTIVE, ERR_INSUFFICIENT_CREDITS]). Sibling assign_invalid_state_beats_insufficient_credits IS strictly asserted to ERR_INVALID_STATE (state-check ranked above business rules).

**Audits passed:** all 70 tests carry exactly one Design: tag resolving to a real instance; all 106 PRD citations verified verbatim; all literal expected values recomputed (fees 151000/355000/425000/60000, billing 260000/195001, early-term 390000, composite 81, priority 600.0, rollover 25, health 100).

## Step 6: Generate Implementation — 2026-06-29T03:22:10.793Z

**Framework / storage:** Python 3 + Flask 3.0.3. Storage in-memory only — single global Store (db.py) one dict-per-entity keyed by UUID + LogicalClock. Nothing on disk; state wiped on start.sh re-launch. No entity seeding at startup.

**Files produced** (23 source files, ~2,680 LOC): start.sh, requirements.txt, app.py, errors.py (22-code catalog), clock.py, db.py, response.py, auth.py, helpers.py, calc.py (11 calcs Decimal-based), services.py (cascades) + routes/ (resellers, clients+audits, keywords+snapshots, retainers, contracts, sprints, deliverables, campaigns, disputes, gbp, reports, clock_ctl).

**Endpoints implemented:** all 75 from PRD §4.

**State machines (9):** Client, Retainer (cyclic rollover), Contract (renew/expire fork), Sprint, Deliverable, AdCampaign (dual lifecycle+billing dims), AdSpendDispute, GbpListing, KeywordTarget. Cascades: client pause/resume, depth-3 churn, retainer activate bubble-up, rollover→contract auto-renew/expire.

**Calculations (11):** all money in integer cents via decimal.Decimal with ROUND_FLOOR/ROUND_HALF_UP.

**Validation order** per PRD §2.7: auth(401)→role(403)→ownership(403)→existence(404)→body(422)→state(409)→OCC(412)→business rules. OCC on expected_retainer_version → ERR_STALE_RETAINER_VERSION (412).

**start.sh:** set -euo pipefail, cd to script dir, guarded dep install, exec python3 app.py binding 0.0.0.0:$PORT (default 10000), threaded, foreground.

**Verification:** Booted via bash start.sh; 4 smoke suites (60+ assertions) all passing.

## Step 7: Run Tests and Iterate — 2026-06-29T03:57:19.000Z

The very first sweep came back fully green across all 8 rounds with no flakiness. No diagnosis, deletions, or fixes were required.

Summary:
- Iterations run: 1
- Tests deleted: none
- Fixes applied to test_helpers/: none
- Fixes applied to test_suite/: none
- Fixes applied to implementation/: none
- Final sweep result: all 8 rounds passed == total (70/70 in every round; failed=0, errors=0, skipped=0 across rounds 1–8).

(Sweep executed as two waves of four for single-task anti-saturation; results.1.json … results.8.json all show passed=70/total=70.)

## Step 8: Finalize PRD — 2026-06-29T03:57:19.000Z

SKIPPED per skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already uniquely determined every behavior the implementation exhibits, so no PRD_FINALIZED.md is produced. Step 9 therefore starts from PRD.md.

## Step 9: Complete PRD — 2026-06-29T04:03:00.000Z

PRD_COMPLETED.md is written to disk with all edits applied. Here is the worklog summary.

---

**Source vs result**
- Source: `PRD.md` (PRD_FINALIZED.md absent) — 308 lines, 51260 chars
- Result: `PRD_COMPLETED.md` — 308 lines, 54091 chars (char-delta +2831; all edits are in-paragraph, no lines added/removed)

**Counts**
- Ambiguity-pins: 10
- Mismatch-revisions: 1

**Changes** (`{PRD section} — {insert|revise} — {kind} — {what} — {impl ref}`)
- §2.1/§2.7 — revise — ambiguity — Pinned that both `X-User-Role` (recognized role) and `X-User-ID` (present, non-empty) are mandatory for *every* role including opaque operators, and role-header error precedes id-header error — `auth.py:34-40`
- §2.3 — insert — ambiguity — Pinned that out-of-range/non-integer `limit`/`offset` and negative `offset` fail `ERR_INVALID_REQUEST`, that list ordering tie-breaks by insertion order, and the exact `has_more`/`total_count` formulas — `helpers.py:195-223`, `response.py:47-48`
- §2.8 — insert — ambiguity — Pinned `expected_retainer_version` is a required integer (`ERR_INVALID_REQUEST` if missing/non-int, priority 5) and the priority-6 state check precedes the priority-7 concurrency check — `routes/retainers.py:147-153`, `routes/deliverables.py:100-111`
- §2.11 — insert — ambiguity — Pinned `to_iso8601` is required (invalid → `ERR_INVALID_REQUEST`) and the clock-set call returns `200 OK` with an empty `data` object (does not echo clock state) — `routes/clock_ctl.py:26-31`
- §3.3 — revise — ambiguity — Pinned `total_traffic` is scoped to snapshots of *this client's* keyword targets (any status) within the half-open window — `services.py:189-197`
- §3.4 — insert — ambiguity — Pinned that creating a deliverable against a `SUSPENDED` retainer fails `ERR_INVALID_STATE` — `routes/deliverables.py:39-40`
- §3.6 — insert — ambiguity — Pinned `expected_retainer_version` as required integer at priority 5/7 and the fixed business-rule evaluation order for assign (retainer-ACTIVE → sprint-state → window → capacity → credits), where wrong sprint state is `ERR_INVALID_STATE` — `routes/deliverables.py:100-139`
- §3.7 — insert — ambiguity — Pinned `amount_cents` is a required non-negative integer (0 allowed) and that record-spend is permitted regardless of lifecycle/billing status — `routes/campaigns.py:128-141`
- §3.8 — revise — ambiguity — Reconciled "recomputes management_fee_cents" on UPHELD with the §3.7 freeze: the fee is recomputed only while the campaign is `UNBILLED`; an `INVOICED`/`SETTLED` fee stays frozen even though spend is clawed back — `routes/disputes.py:107-112`
- §3.9 — revise — mismatch — Corrected "starts with optimization_score of 0": the score is computed at creation from the completeness signals, so a new `UNVERIFIED` listing scores 50 (or 75 if client already `ACTIVE`); also pinned `location_name`/`service_area` required non-empty — `routes/gbp.py:32-44`
- §3.9 — revise — ambiguity — Pinned that optimize recomputes `optimization_score` before applying the ≥80 threshold check — `routes/gbp.py:105-108`

Notable verified non-issues (impl already matches PRD, left unchanged): assign OCC-vs-business-rule precedence (§2.7-consistent), pause/resume/churn cascades incl. PAUSED-churn not ending campaigns, retainer SUSPENDED-reactivation not re-granting, contract renewal/expiry fork, snapshot best_rank rule, credit-ledger reconciliation, and all read-side recomputes (client/retainer/sprint/campaign/listing/keyword). Tests at the task level (not workspace) were used only as auxiliary cross-reference; test_05 explicitly notes §2.7 leaves assign business-rule order unpinned, which I have now pinned to the impl's order.
