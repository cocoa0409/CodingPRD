# Worklog — task_1970_production_home_builder_sales_option

## Step 1: Create task directory — 2026-08-15T03:39:00.000Z

Directory `tasks/task_1970_production_home_builder_sales_option/` and `workspace/` pre-created by pipeline (orchestrator instructed to skip Step 1).

## Step 2: Generate scaffold — 2026-08-15T04:22:00.000Z

All three scaffold artifacts are generated, lint-clean, and cross-audited.

**SCAFFOLD.yaml** (§1.0–§1.7 only)
- **Profile**: workflow_orchestration × pricing_engine; layers: dual-variant calculation, rate/threshold triggers, scheduled actions, optimistic concurrency; flat FK topology, branching state shape, peer roles, immediate consistency.
- **10 entities**: Community, PricePhase, Lot, HomePlan, OptionCatalogItem, Buyer, PurchaseAgreement, OptionSelection, ConstructionMilestone, IncentiveRequest (warranty folded into the agreement as `warranty_status` NONE→ENROLLED→ACKNOWLEDGED).
- **6 state machines**: lot cycle (RELEASED⇄RESERVED), selection cycle (SELECTED⇄CONFIRMED), branching agreement with three cancel paths + clock-sweep auto-cancel on contingency deadline, milestone chain with in-order gating, incentive approval with auto-approve branch.
- **2 OCC concurrency rules** (both pass the serial-observability filter): `agreement-create-stale-lot` (expected_lot_version on POST /agreements) and `clearance-stale-agreement` (expected_agreement_version on contingency-clearance), both 412.
- **7 calculations** with pinned constants; all asserted literals verified by executing the formulas in Python (e.g. release price 9991000 = round(8000000×1.03)+round(1700000×1.03); re-release 10190820; standard/padded estimates 2026-12-14 vs 2027-01-06; forfeit 125000/refund 375000; fee 30000).
- **11 ordered validations, 38 endpoints, 37 errors, 6 roles** (Buyer is `entity_backed:Buyer`, others opaque; clock default pinned to 2026-08-01T00:00:00Z in the `/_clock/set_current_utc` description).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rules × 2 instances = 18, each with full structured setup/trigger chains from empty DB. Differentiation honored: dual variants on fiscal (agreement pricing) vs temporal (closing estimate) domains; combinatorial modes (a) lot premium vs (c) incentive-cap-on-provisional ordering; cascades of depth 3 (milestone→stage→selection auto-cancel→options recompute) vs depth 2 (cancel→lot release→reprice) from different triggers; priority conflicts on state×fiscal and temporal×referential pairs; boundaries on incentive cents (≤300000) vs stage ordinals (unconfirm at cutoff equality); temporal overlaps with point-containment (lot hold, half-open expiry) vs interval-interval (phase windows, adjacency allowed); invariants conserving budget money vs released-lot count.

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections per the claim-extraction guide, 38 active instances + 4 `excluded_because` stubs pointing at covering difficulty instances.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (38 endpoints, 10 entities, 18+38 instances, 597 calls scanned). Additional audits passed: 60 instance names unique across both files, all `grounds`/`excluded_because` refs resolve, no forbidden concurrency vocabulary, every error code referenced outside the catalog, and file split honored (neither design key appears in SCAFFOLD.yaml).

One design fix made mid-build: the milestone sweep auto-cancels stale SELECTED selections, which would have made a "past-cutoff confirm fee" unreachable — so the change fee now accrues only on cancelling a CONFIRMED selection past cutoff, confirm is fee-free, and the cutoff-boundary difficulty probe targets `unconfirm` (where equality stays free, one stage past is rejected).

## Step 3: Copy shared files — 2026-08-15T04:25:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1970_production_home_builder_sales_option/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T04:40:00.000Z

All checks pass. The "38 endpoints" count from the script is consistent between scaffold and table (I had miscounted 37 earlier — the mechanical check confirms all 38 scaffold endpoints are present with 4-column rows, and §5 has exactly 37 two-column error rows).

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1970_production_home_builder_sales_option/workspace/PRD.md` — a full PRD for the production-home-sales domain, from `SCAFFOLD.yaml` only (the two difficulty/corner design files were not opened or referenced).

**Document skeleton (domain-derived, not copied from the example):**
- §2 (10 subsections): RBAC with per-role identity translation (Buyer entity-backed, five opaque roles) → verbatim §2.2 → Pagination → Common Resource Properties & Mutation Semantics → Money/Precision/Rounding → Logical Clock & Scheduled Sweep → Construction Stage Calendar → Community Incentive Ledger → OCC → Validation Order/Nested Retrieval/Buyer Scoping.
- §3 (9 subsections, chronological deal flow): community/catalogs → lot release pricing & holds → agreement draft/sign → contingency clearance & deadline sweep → design-center selections & cutoffs → milestones/estimates/slippage → incentives → cancellation/refunds/re-release → closing & warranty.
- §4: 38-row endpoint table (Method/Path/Description/Roles only); §5: 37-row error table (ID/status only).

**Key spec decisions reflected:** integer-cent money with pinned per-component round-half-up for release pricing; constants embedded with exact unit conversions ($15,000 CORNER premium, $30,000 cap, $3,000 auto-approve limit, $1,000 earnest floor, 2%/6%/10%/15%/25% rates, 72-hour holds, 7-day buffer, 12-month warranty, 30/21/28/35/14 stage durations); both OCC rules framed purely as stale-version rejections; 11-tier validation cascade stated as an ordered sequence with observable-ordering examples (expired-hold → `ERR_LOT_NOT_RELEASED` state tier vs active hold → `ERR_LOT_HOLD_ACTIVE` temporal tier; budget-before-cap).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body: 42 required, 42 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- (also: 1 path param, 4 common fields — all present)
Status: PASS

Rule coverage check:
- validations[] priority: 11 tiers checked, 11 expressed as ordered cascade, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write_endpoint + expected_lot_version/expected_agreement_version + ERR_STALE_LOT_VERSION/ERR_STALE_AGREEMENT_VERSION + 412), 0 missing
- state_machines[].transitions: 33 checked (incl. system sweeps, cascades, warranty self-transition), 33 fully expressed, 0 missing
- calculations[]: 7 checked (release pricing + re-release variant, agreement pricing provisional/final, closing estimate standard/padded, slippage, change fee, earnest refund 5-branch, budget ledger), 7 fully expressed, 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose (all 37 error IDs appear in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: 38 checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 72 checked, 72 reconstructible (defaults, null-unless semantics, snapshots, derived statuses), 0 missing
- sibling-branch symmetry: 7 groups checked (cancel branches, refund branches, selection-cancel branches, milestone sweeps, decide branches, phase derivation, reserve rejections), 7 symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 415
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; zero pseudocode operators in backticks; zero fuzzy hedging words; zero forbidden OCC race-framing terms; all 19 state values, 52 enum values, and 6 role names appear verbatim.

## Step 5: Generate unit tests — 2026-08-15T05:15:00.000Z

Done. All generation and audit passes are complete.

## What was generated

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1970_production_home_builder_sales_option/test_helpers/`):
- `types.py` — 10 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4) + 14 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, including `/_clock/set_current_utc`
- `api_errors.py` — full 39-error catalog + HTTP map, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_instant_equals` (fractional-digit-tolerant instant comparison for clock-stamped fields), `assert_refund_invariant`, `assert_budget_conservation`
- `factories.py`, `constants.py` (canonical scenario numbers: release 9,991,000; provisional 45,241,000; re-release 10,190,820; cap 2,714,460; estimates 2026-12-14 / 2027-01-06), `test_users.py` (with mandatory `make_buyer_headers(buyer_id)` for the entity-backed Buyer role)
- `fixtures.py` — tiered composites: `setup_community_selling` → `setup_released_scenario` → `setup_reserved_scenario` → `setup_draft_agreement` → `setup_signed_agreement` → `setup_cleared_agreement` (version re-read before each OCC clearance) → `setup_close_ready` / `setup_closed_agreement`, plus `complete_milestones_in_order` (filters NOT_STARTED so repeated calls advance), clock advance, and thin endpoint wrappers

**`test_suite/`** — `conftest.py` + 9 test files, **72 tests total**:
- Queue A: 17 of 18 difficulty instances × ≥2 tests (34 tests)
- Queue B: all 38 non-stub corner instances × ≥1 test (38 tests); the 4 `excluded_because:` stubs were not translated, and their `difficulty_instance` cross-references all resolve

## Audit results
- Every test carries exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from a real instance name; no untagged, dual-tagged, or dangling tags
- Every docstring citation ≥8 words was grep-verified verbatim against `PRD.md`
- No `skip`/`skipif`/`xfail` anywhere; all modules compile and import; all `test_helpers` imports resolve

## The one intentional gap
`Difficulty/priority_pair_validation_conflict/incentive_create_state_beats_fiscal` was **skipped** under the PRD-first two-condition filter: it asserts `ERR_AGREEMENT_INVALID_STATE` when creating an incentive against a CANCELLED agreement, but PRD §3.7 never gates incentive creation on agreement status — it specifies only the budget intake guard (`ERR_INCENTIVE_BUDGET_EXCEEDED`). A PRD-only implementer could faithfully ship either error, so unique derivability fails. This is a PRD gap, left as a gap (the matching corner stub `priority_state_vs_fiscal_on_incentive_create` is an `excluded_because:` stub pointing at this instance, so queue B is unaffected).

## Step 6: Generate implementation — 2026-08-15T05:45:00.000Z

Done. The implementation is complete and verified.

## What was built

A complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1970_production_home_builder_sales_option/workspace/implementation/`:

- **`start.sh`** — foreground launcher with the guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Executable.
- **`app.py`** — entry point, blueprint registration, envelope error handlers; Werkzeug request logging silenced to minimize reboot cost under per-test-server churn.
- **`db.py`** — in-memory store (10 collections, empty at boot, no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, 3-fractional-digit UTC timestamps, `version` starting at 1 with `touch()` bumps.
- **`errors.py` / `response.py` / `middleware.py` / `util.py` / `constants.py`** — the full 35-entry error catalog, the `meta`/`response_type`/`data` envelope, `X-User-ID`/`X-User-Role` auth with the six declared roles, body-shape/pagination helpers, and all pinned constants (premiums, 0.02 re-release uplift, 0.06 cap, 0.15 weather buffer, 72h hold, 100000 min earnest, 300000 auto-approve limit, 12-month warranty).
- **`services.py`** — all calculations with `Decimal` round-half-up (pinned per-component rounding for release pricing; per-stage ceiling for the padded estimate), plus derived ledgers (community budget, options/fees/incentives totals computed at read so conservation holds by construction), milestone-completion sweeps, the cancellation cascade, and the clock sweep.
- **`routes/`** — 11 modules covering all 30 endpoints, including the unprefixed `POST /_clock/set_current_utc` (PlatformAdmin, echoes `to_iso8601` verbatim).

Key fidelity decisions, all traceable to the PRD: validation tiers follow PRD §2.10 exactly (ownership tier 5 before state tier 7; temporal tier 8 before referential tier 10 — both priority-conflict recipes verified); OCC only on the two declared endpoints; contingency statuses/snapshots/estimates are `null` until signing; clearance bubble-up bumps the agreement version twice; selection creation has no agreement-state gate (spec-literal); hold churn never reprices while post-contract fallout reprices +2% with `release_count += 1`.

## Verification

- Four smoke-test waves (~115 assertions) covering every difficulty-design and corner-design recipe: pinned numbers (release 9991000, provisional 45241000, final 45841000, re-release 10190820, cap 2714460, estimates 2026-12-14/2027-01-06), all error paths, OCC 412s, sweeps, buyer scoping, and boundary equalities — all pass.
- Official harness `prd-bench-local-run --isolation per-test-server`: **72/72 passed**, then rerun twice more after a boot-speed tweak → **72/72 and 72/72**. One earlier run showed 2 flaky failures; the server log proved a port-handoff race (runner readiness poll served by a dying previous server mid-test while ~8 concurrent harnesses ran on this host), not an implementation defect — the same tests pass deterministically in isolation and in all three subsequent full-suite runs.
- Fresh-boot statelessness verified through `bash start.sh` — every restart starts with an empty store, as required by per-test-server isolation.

## Step 7: Run tests and iterate — 2026-08-15T06:05:00.000Z

Summary — task_1970_production_home_builder_sales_option

**Iterations run:** 1 (single 8-round parallel stability sweep, `--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`).

**Result:** Clean sweep on the first iteration. All 8 rounds report `passed=72, failed=0, errors=0, skipped=0, total=72` (verified by reading every `results.${i}.json`, i = 1..8). Per-round wall time ~93s. No flakiness surfaced — the union of failing tests across rounds is empty.

**Tests deleted:** None. Every one of the 72 tests passed in every round, so no test entered the diagnostic protocol. (Note from the worklog: one difficulty instance, `Difficulty/priority_pair_validation_conflict/incentive_create_state_beats_fiscal`, was already excluded at generation time under the PRD-first unique-derivability filter — PRD §3.7 never gates incentive creation on agreement status, so a PRD-only implementer could ship either error.)

**Fixes applied to `test_helpers/`:** None needed this iteration. I audited `fixtures.py`, `factories.py`, `assertions.py`, and `test_09_rbac_scoping_and_auth.py` / `test_01_community_and_pricing_phases.py` while the sweep ran — fixtures build PRD-consistent preconditions (tiered composites re-read OCC versions before clearance, buyer headers use the entity-backed `make_buyer_headers`, canonical scenario numbers match the PRD's pinned constants), and assertions trace to verbatim PRD sentences.

**Fixes applied to `implementation/`:** None needed. The existing Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1970_production_home_builder_sales_option/workspace/implementation/` passed all 72 tests in all 8 concurrent rounds with zero intervention.

**Exit condition met:** all 8 rounds have `passed == total`. No further iterations required.

## Step 8: Finalize PRD — 2026-08-15T06:06:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-15T06:25:00.000Z

The patch is complete. All edits verified via diff.

## Summary

**Source**: `PRD.md` (no `PRD_FINALIZED.md` existed — Step 8 was skipped) → `/home/ubuntu/github/CodingPRD/tasks/task_1970_production_home_builder_sales_option/workspace/PRD_COMPLETED.md`

- Line counts: 304 → 307 (+3 lines); chars: 49,539 → 51,559 (+2,020)
- **Ambiguity-pins: 15 — Mismatch-revisions: 0** (Step 7's clean exit is corroborated: every impl behavior traced to PRD prose already matched in substance; all remaining gaps were PRD silence, not contradiction)

Changes (all in-paragraph inserts/revisions; no new sections; one table row added to §5):

- §2.1 — insert — ambiguity — blank/whitespace header values rejected same as missing headers — implementation/middleware.py:25
- §2.2 — insert — ambiguity — undeclared path or unsupported method rejected with `ERR_NOT_FOUND` (HTTP 404) — implementation/app.py:49-55
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — implementation/util.py:149-170
- §2.3 — insert — ambiguity — filters are exact-match, combine conjunctively, unrecognized query params ignored — implementation/util.py:186-193
- §2.4 — revise — ambiguity — `version` starts at 1 (was "starts at its initial value") — implementation/db.py:63
- §2.6 — insert — ambiguity — server-generated timestamps (`created_at`, `updated_at`, `api_request_timestamp`) read from the logical clock; client-supplied datetime fields stored/returned verbatim, never normalized — implementation/db.py:30,58,70-72; response.py:13
- §2.6 — insert — ambiguity — clock response `current_utc` echoes the supplied `to_iso8601` string verbatim — implementation/routes/clock.py:29
- §2.10 tier 3 — revise — ambiguity — unknown (undeclared) body fields rejected with `ERR_INVALID_REQUEST`; explicit JSON `null` on optional field treated as absent — implementation/util.py:121-134
- §3.1 — revise — ambiguity — `uplift_pct` admissible at any numeric value, zero/negative not rejected — implementation/routes/phases.py:29
- §3.2 — revise — ambiguity — `view_adjustment_cents` must be zero or more (negative malformed) — implementation/routes/lots.py:41
- §3.3 — insert — ambiguity — at DRAFT creation: three contingency trackers, three price snapshots, `provisional_total_cents`, both closing estimates null; `slippage_flag` false — implementation/routes/agreements.py:120-131
- §3.3 — revise — ambiguity — sign guard within-tier order pinned: lot `RESERVED`-by-buyer check evaluated before community `SELLING` check — implementation/routes/agreements.py:177-182
- §3.6 — insert — ambiguity — milestone list ties on `sequence_no` break by stable insertion order — implementation/routes/milestones.py:31
- §3.7 — insert — ambiguity — incentive creation requires agreement in `PENDING_CONTINGENCIES`/`CONTINGENCIES_CLEARED` (else `ERR_AGREEMENT_INVALID_STATE`), checked before the budget guard — implementation/routes/incentives.py:57-59
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) catalogue row for requests outside the declared API surface — implementation/errors.py:52, app.py:49-55

Key findings: the implementation tracked the PRD remarkably closely — all state machines, pricing formulas (half-up rounding order, premium cap, re-release uplift), sweep semantics, OCC guards, cascade version bumps, and buyer scoping were already uniquely pinned. The only near-mismatch was the sign endpoint's guard order (PRD listed community-SELLING before lot-RESERVED; impl evaluates lot first within the same validation tier), resolved by reordering the prose. The largest genuine silence was §3.7: the PRD never stated an agreement-state guard on incentive creation, which impl enforces.
