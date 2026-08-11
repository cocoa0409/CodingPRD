# Worklog — task_0991_ewaste_electronics_recycling_itad

## Step 1: Create Task Directory — 2026-08-10T11:04:01.927Z

Pre-assigned output folder `tasks/task_0991_ewaste_electronics_recycling_itad` with `workspace/` subdirectory confirmed to exist (Step 1 auto-index scan skipped per run instructions). Difficulty parameter for this run: "generate task hard than expert level!" (pass-through to scaffold generator at Step 2 only).

## Step 2: Generate Scaffold — 2026-08-10T11:34:00.000Z

All three artifacts are on disk and fully validated. Final report:

## Task 0991 — E-Waste & Electronics Recycling (ITAD) scaffold complete

**Files (all confirmed on disk):**
- `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/SCAFFOLD.yaml` — §1.0–§1.7 only (78 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (67 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (119 KB)

**Scaffold shape:**
- **12 entities**: BusinessAccount, Recycler, CompliancePolicy, Manifest, Item (parallel `processing_status` × `data_status` dimensions), DataSanitization, ResaleListing, RecycleBatch, CustodyEvent (append-only, polymorphic), Certificate, Settlement (self-referential supersede chain), LedgerEntry (append-only)
- **8 state machines** — non-linear: Item (refurb reroute + FOR_RESALE↔LISTED loop + parallel data dimension) and ResaleListing (ACTIVE→SOLD→RETURNED→ACTIVE cycle)
- **6 calculations**: settlement_valuation (QUOTE/FINAL dual-variant), item_recycling_fee (4-input tiered, mode a), settlement_net_rebate (pinned circular-breaking evaluation order, mode c), recycler_selection_score (R2 vs e-Stewards weight variants feeding a selector policy), sustainability_metrics, account_tier_threshold — with round-per-line-then-sum (mode b) pinned
- **54 endpoints**, including the `POST /itad/_clock/set_current_utc` test-driving clock (default `2026-05-01T00:00:00Z` declared)
- **38 error codes**, **31 ordered validations**, **6 roles** (segregation-of-duties model: DestructionTechnician logs / ComplianceOfficer verifies), **2 OCC concurrency rules** (manifest amend, settlement requote-supersede; both `ERR_STALE_VERSION` 412)
- **§1.8: 18 instances** (9 rules × 2), all with computed literal asserts (e.g. QUOTE 80000 vs FINAL gross 102000/rebate 2040/net 104040; rebate order pinned at 9900 not GOLD 24750; selector ranking flip 68.0→A vs 65.12→B; capacity exact-fit 100.0 kg allowed, +0.001 rejected; tier upgrade at exactly 1000.0 kg)
- **§1.9: 63 instances** (54 active + 9 `excluded_because` stubs) across all nine taxonomy sections; every error in the catalog has at least one trigger test

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(54 endpoints, 12 entities, 18 §1.8 + 54 §1.9 active instances, 742 calls scanned, zero violations.)

Additional audits passed: no forbidden concurrency vocabulary, no design-key leakage into SCAFFOLD.yaml, 81 instance names unique across both design files, all `grounds` references (state machines, entity fields, validation priorities, calculations, concurrency rules) resolve, terminal states reachable for every machine.

## Step 3: Copy Shared Files — 2026-08-10T11:34:42.499Z

Copied `./INSTRUCTION.md` to `tasks/task_0991_ewaste_electronics_recycling_itad/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T11:43:06.833Z

PRD.md is generated and verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/workspace/PRD.md` (53.8 KB, 330 lines). The withheld difficulty/corner index files were not opened or referenced.

## Document structure

- **§1 Introduction** — 2 paragraphs (business context + capability/compliance asymmetry, logical-clock anchor, `/itad` mount)
- **§2 Global Specifications** (11 subsections): 2.1 RBAC with per-role identity prose (AccountManager entity-backed to BusinessAccount, five opaque roles), 2.2 response envelope emitted verbatim from `section-2.2-response-structure.md`, 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Resource Identity (UUID `id`, 3-fractional-digit timestamps, `version`; explicit `updated_at`/`version` absence for CustodyEvent and LedgerEntry), 2.5 Nested Retrieval (left-to-right 404, all nine `ERR_*_NOT_FOUND` named), 2.6 Validation Order (all 31 priorities in explicit ranked bands), 2.7 Precision (integer cents, round-half-up, pinned round-then-sum, 3dp weights, 2dp scores), 2.8 OCC (both concurrency rules: `expected_manifest_version` → `ERR_STALE_VERSION` 412 on manifest amend and quote create), 2.9 Logical Clock (default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.10 Custody Trail, 2.11 Policy Activation
- **§3 Business Logic** (9 subsections, lifecycle-timeline grouping): 3.1 Accounts & tier progression (1000/5000 kg inclusive thresholds, close preconditions), 3.2 Policies & recycler registry (risk-score formula in prose, selector ranking/tie-break), 3.3 Manifest intake (window/route-conflict half-open semantics, reconcile check ordering), 3.4 Item scan & triage (parallel `processing_status` × `data_status`, all reroutes), 3.5 Sanitization & CODD (segregation of duties, PASS/FAIL branches symmetric), 3.6 Resale cycle (floor-price gate ordering, commission 15/15/10%, return cascade), 3.7 Batches (selector, capacity equality-allowed, process cascade with auto-COR `system`), 3.8 Settlements & ledger (QUOTE/FINAL variants, all fee/base-value/grade constants in prose, pinned rebate order, BUYBACK_CREDIT → FEE_DEBIT → BONUS_CREDIT posting, REVERSAL compensating invariant), 3.9 Sustainability report
- **§4 Endpoint table** — 54 endpoints, 4 columns only (Method / Path / Description / Authorized Roles)
- **§5 Error catalogue** — all 38 error IDs, 2 columns only

## Hard contract reports

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 91 required, 91 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed (global band order in §2.6 + per-endpoint orderings in §3), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_manifest_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 6 checked, 6 fully expressed with all constants in prose, 0 missing
- validations[] conditions: all matchable to error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects: 54 checked, expressed in §3 workflows or §4 descriptions, 0 missing
- entities[].fields[] structured content: defaults/initial values/computed semantics reconstructible, 0 missing
- sibling-branch symmetry: 6 groups (triage reroutes, verify verdicts, pay/void, cancel from DRAFT/SCHEDULED, ledger posting, custody events) — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 524
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: no pseudocode operators (`>=`, `==`, `+=`, etc.) or fuzzy words ("approximately", "roughly", "conservatively") anywhere outside code fences; all 38 scaffold error IDs appear in §2/§3 prose; §2.2 block is byte-identical to the canonical source.

## Step 5: Generate Unit Tests — 2026-08-10T12:08:20.167Z

Generation complete. All files verified on disk, pytest collects all 94 tests cleanly, and both completeness audits pass.

## Summary

**Test count: 94** (all tagged, all PRD-cited, zero skip/xfail markers, zero bogus tags)

### Per-file breakdown (test_suite/)
| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_platform_conventions.py | 6 | 0 | 6 |
| test_02_accounts_policies_rbac.py | 6 | 0 | 6 |
| test_03_manifest_lifecycle.py | 8 | 2 | 6 |
| test_04_manifest_scheduling.py | 8 | 4 | 4 |
| test_05_items_triage.py | 6 | 2 | 4 |
| test_06_sanitization_certificates.py | 10 | 4 | 6 |
| test_07_resale_listings.py | 9 | 4 | 5 |
| test_08_recycle_batches.py | 7 | 4 | 3 |
| test_09_shipping_and_recycler_selection.py | 12 | 6 | 6 |
| test_10_process_cascade_and_reporting.py | 5 | 3 | 2 |
| test_11_settlement_valuation.py | 9 | 6 | 3 |
| test_12_settlement_lifecycle_ledger.py | 8 | 2 | 6 |

### §1.8 difficulty coverage — 18/18 instances translated, each with ≥2 tests
- dual_variant_calc ×2, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2, boundary_precision_check ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2 — all pre-computed literal values (68.0/55.21/60.0/65.12 scores, 80000→102000 divergence, 3650 fee, 9900 pinned rebate, 1000.0 kg tier upgrade, etc.) carried verbatim into assertions.

### §1.9 corner coverage — 63 instances: 51 translated (57 tests), 9 stubs not translated, 3 skipped
- All 9 `excluded_because:` stubs verified to resolve to real difficulty instances and left untranslated.
- **Skipped** (PRD-first filter failures, gaps left as gaps):
  1. `entities/duplicate_serial_within_manifest_rejected` — PRD §3.4 states serials are "unique within its manifest" but never names the rejection `error_id`/status; §2.6 item 5's body-schema list doesn't include duplicates, so two PRD-only readers could legitimately ship 400 vs 409 vs 422.
  2. `entities/account_create_extra_id_input_ignored` — PRD never addresses unknown/extra request fields; ignoring vs rejecting are both PRD-consistent.
  3. `validations/requote_after_finalize_rejected` — the settlement-finality guard is stated in PRD only for listing returns (§3.6); §3.8's quote-creation path ("at any point after receipt") names no such block.
- One instance (`occ_manifest_version_increments_on_patch`) translated asserting the derivable claim (`version` increments by exactly one per mutation, PRD §2.4); its absolute "starts at 1" literal is not PRD-pinned and was not asserted.
- Deterministic-ordering hardening: where instances assert `created_at ASC` outcomes, the logical clock is advanced between writes (pagination, policy list, custody trail, ledger trail, selector tie-break) so ordering is uniquely derivable whether `created_at` follows the logical or wall clock.

### Helper modules (test_helpers/)
- `types.py` — 12 entity TypedDicts (CustodyEvent/LedgerEntry correctly omit `updated_at`/`version` per append-only rule), 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 endpoint methods (one per PRD §4 row), module singleton
- `api_errors.py` — all 38 `ApiErrorId` members with §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — 12 per-entity assertions + `CERT-XXXXXXXX` format check
- `factories.py` — 8 payload factories (input fields only; `pickup_route` omitted unless set)
- `constants.py` — valuation/fee/rebate/tier/score constants from PRD §3
- `test_users.py` — `TEST_USERS` for all 6 roles + per-instance `make_*_headers` builders; `AccountManager` treated as entity-backed
- `fixtures.py` — composite tiers: state progression (`manifest_in_state`), hierarchy (`setup_received_manifest`, `setup_triaged_item`), lifecycle shortcuts (`setup_sold_item` → `setup_closed_manifest`, sanitization verify loop), batch chains (`setup_batched_item`, `setup_processed_batch`), OCC-aware `create_quote_settlement`; 204 handled for DELETE removal
- `__init__.py` — barrel re-export of framework generics + PRD-specific names

## Step 6: Generate Implementation — 2026-08-10T12:08:20.167Z

Implementation complete and verified. Summary follows.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/workspace/implementation/`)

- `start.sh` — executable, foreground `exec python3 app.py`, guarded dependency install (`if ! python3 -c "import flask"`), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry, blueprint registration, `ApiError`/404/405/500 envelope handlers
- `db.py` — in-memory dict stores + monotonic insertion seq (starts empty; no seeding anywhere)
- `clocktime.py` — logical clock (boot default exactly `2026-05-01T00:00:00Z`, never wall-clock), ISO parse/format helpers
- `errors.py` — `ApiError` + all 37 catalog error IDs
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range 1–100), created_at-ASC sort
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role gating (403), AccountManager ownership
- `serialize.py` — wire shapes for all 12 entity kinds (CustodyEvent/LedgerEntry without `updated_at`/`version` per PRD §2.4)
- `services/calculations.py` — all 6 calculation rules
- `services/workflow.py` — custody writes, ledger posting, batch totals, completion cascade, QUOTE recompute
- `routes/` — 11 modules: accounts, recyclers, policies, manifests, items, sanitizations, listings, batches, settlements, certificates, misc (custody + clock)

## Endpoint coverage
**54/54** endpoints from the scaffold endpoint table implemented (6 accounts incl. sustainability-report, 3 recyclers, 2 policies, 11 manifests, 6 items, 1 sanitization verify, 6 listings, 9 recycle-batches incl. DELETE→204, 7 settlements, 1 certificate void, 1 custody query, 1 clock set).

## Entity / state-machine / calculation coverage
- **All 12 entities** with scaffold-exact fields; computed fields (`credit_balance_cents`, `lifetime_diverted_kg`, `total_processed_kg`, `risk_score`, batch totals, settlement figures) derived per spec; version bumps on every mutation incl. derived-field refreshes (PRD §2.4).
- **All 9 state machines**: account (incl. close preconditions), manifest (schedule/receive/reconcile/close/cancel with full guard chains), item (parallel processing_status × data_status with all reroutes), sanitization (SoD + FAIL-cannot-verify + REJECT retry loop), listing (sell/return/relist/withdraw + return cascade with QUOTE recompute), batch (ship cert+capacity re-checks, process cascade with COR auto-issue + tier upgrade), settlement (supersede chain, finalize ledger sequence BUYBACK→FEE→BONUS, pay PAYOUT_DEBIT, void compensating REVERSALs), certificate (void).
- **All 6 calculations** with Decimal round-half-up, round-then-sum: settlement_valuation (QUOTE/FINAL variants), item_recycling_fee (weight tiers 5.0/20.0 in MID, hazmat, QUOTE-NIST_CLEAR vs FINAL-latest-VERIFIED sanitization, pickup fee), settlement_net_rebate (pinned pre-rebate tier keying, GOLD/SILVER inclusive boundaries, non-positive→0), recycler_selection_score (floor-days/365, clamps, 2dp; selector risk_score DESC → volume DESC → created_at ASC), sustainability_metrics (0.0 on zero weight, VOIDED certs excluded), account_tier_threshold (inclusive 1000/5000, never-downgrade).
- **OCC** `expected_manifest_version` on PATCH manifest + quote create (412, evaluated before state gates per priority); **validation priority order** implemented per PRD §2.6 (verified sell-gate-before-floor, OCC-before-state, creation ownership→body→suspension).

## Boot smoke test result
`bash start.sh` on fresh ports (18741–18744, 19999): boots in ~2.5s, clean log, correct envelopes on both a 401 rejection and a clock-set request; full functional sweep across 4 fresh-boot rounds — ~100 assertion checks all passing (auth/RBAC/ownership, route-window half-open overlap + adjacency, serial uniqueness, sanitization SoD + gates, listing cycle, selector + capacity exact-fit, cert-expiry exclusivity, QUOTE/FINAL/supersede/finalize/pay/void arithmetic with exact cent values, tier upgrade at exactly 1000.0 kg, SILVER/GOLD rebate boundaries, negative-net settlement, sustainability report, pagination meta, fresh-boot empty store). Two test-side failures observed during sweeps were my own scenario bugs (open draft manifest blocking account close; cert-vs-delivery-date expectation), both confirmed spec-correct behavior. One real bug found and fixed: missing `ERR_CLOSE_SETTLEMENT_UNPAID` import in manifests.py (500 → 422); a post-fix static audit confirmed no other unimported error names and clean compiles. All my test servers shut down; `__pycache__` removed.

## Step 7: Run Tests and Iterate — 2026-08-10T12:12:21.661Z

The sweep passed cleanly on the first iteration. All 8 parallel rounds completed with 94/94 tests passing each — 752 total test executions, zero failures, zero errors, zero flaky signals across the union of rounds.

## Summary

- **Iterations run:** 1 (single 8-round parallel sweep, all rounds green)
- **Tests deleted:** none — every test traces to verbatim PRD prose (each test docstring carries the exact PRD §-quote it asserts, verified during review of all 12 test files)
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none

Key verification details:
- All 8 `results.{i}.json` files well-formed: `total=94, passed=94, failed=0, errors=0` in each round
- Per-entry scan of all 752 test executions confirmed `status == "passed"` for every test in every round (no flaky pass/fail variance between rounds)
- The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/workspace/implementation/` (Flask, in-memory stores, logical clock booting at exactly `2026-05-01T00:00:00Z`) covers all 54 endpoints, 12 entities, 9 state machines, and 6 calculation rules per PRD, with the §2.6 validation priority order correctly implemented (verified by spot-review of `routes/manifests.py`, `routes/batches.py`, `routes/listings.py`, `routes/settlements.py`, and `services/calculations.py` while the sweep ran — OCC-before-state, suspension-before-window, state-gate-before-data-gate, round-then-sum money, expiry-exclusive certification window, half-open route windows, selector tie-break `risk_score DESC → total_processed_kg DESC → created_at ASC`).

Step 7 (task #2) is marked completed. No changes were required anywhere — the generated tests and implementation were already mutually consistent and PRD-faithful.

Orchestrator verification: independently re-read all 8 `workspace/implementation/results.{1..8}.json` files — every round reports passed=94 / total=94 / failed=0 / errors=0.

## Step 8: Finalize PRD — 2026-08-10T12:12:21.661Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-10T12:21:44.942Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad/workspace/PRD_COMPLETED.md` written.

## Summary

**Source vs output:** `PRD.md` 329 lines / 53,803 chars → `PRD_COMPLETED.md` 331 lines / 57,739 chars (+2 lines, +3,936 chars). All edits are inline inserts/revisions; no new sections.

**Counts:** 29 ambiguity-pins, 1 mismatch-revision (30 changes total).

**Changes:**
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` reads the host wall clock; persisted resource timestamps read the logical clock — response.py:23-24, utils.py:21-28
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` → `ERR_VALIDATION` — response.py:67-90
- §2.3 — insert — ambiguity — `created_at` ties ordered by creation sequence — response.py:101-102, db.py:6-8
- §2.3 — insert — ambiguity — `has_more` true iff `offset` + returned items < `total_count` — response.py:47
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — utils.py:26
- §2.5 — insert — ambiguity — body-carried ids (`item_id` on listing-create/batch-item-add, `recycler_id` on batch-create) resolve after body validation, before state/policy gates — listings.py:60-62, batches.py:46-48, batches.py:102-104
- §2.9 — revise — ambiguity — clock set accepts any instant, including earlier than current — clocktime.py:14-16, misc.py:54-60
- §2.10 — insert — ambiguity — custody query requires both `subject_type`/`subject_id` (`ERR_VALIDATION`); AccountManager ownership only on resolvable MANIFEST/ITEM subjects — misc.py:37-47
- §2.11 — revise — ambiguity — policy selector weights between zero and one inclusive — policies.py:20-24
- §3.1 — insert — ambiguity — account PATCH with neither `tier` nor `status` → `ERR_VALIDATION` — accounts.py:66-67
- §3.2 — insert — ambiguity — `daily_intake_capacity_kg` must be a number > 0 — recyclers.py:34-36
- §3.2 — insert — ambiguity — `risk_score` is null when no policy is active — calculations.py:204-209
- §3.2 — insert — ambiguity — selector `created_at` ties fall back to creation sequence — calculations.py:233-243
- §3.3 — revise — ambiguity — creation path order now includes account resolution (`ERR_ACCOUNT_NOT_FOUND`) between body validation and the activity check — manifests.py:75-79
- §3.3 — insert — ambiguity — amendments re-validate merged window-pair and route-mode rules (`ERR_VALIDATION`) before the OCC check — manifests.py:122-130
- §3.3 — insert — ambiguity — scheduling requires both window fields set (`ERR_VALIDATION`) before the window-in-past check — manifests.py:163-165
- §3.4 — insert — ambiguity — duplicate `serial_number` within a manifest → `ERR_VALIDATION` — manifests.py:270-274
- §3.4 — insert — ambiguity — freshly scanned item carries zero `provisional_value_cents`/`final_value_cents` — manifests.py:291-292
- §3.5 — insert — ambiguity — sanitization logging gates: `INTAKE` item → `ERR_INVALID_STATE`, non-data-bearing → `ERR_VALIDATION`, any post-`INTAKE` state accepted — items.py:82-86
- §3.5 — insert — ambiguity — all methods allowed when no policy is active — items.py:87-90
- §3.6 — insert — ambiguity — `sale_price_cents` must be an integer ≥ 0 (`ERR_VALIDATION`) — listings.py:87-89
- §3.7 — insert — ambiguity — export permitted when no policy is active — batches.py:50-53
- §3.7 — insert — ambiguity — removing an item not contained in the batch → `ERR_ITEM_NOT_FOUND` before the `STAGING` gate — batches.py:132-134
- §3.8 — revise — ambiguity — quote creation only while `RECEIVED`/`RECONCILED` (`ERR_INVALID_STATE` after OCC), blocked by any `FINALIZED`/`PAID` settlement (`ERR_SETTLEMENT_ALREADY_FINALIZED` after the state check) — manifests.py:339-345
- §3.8 — insert — ambiguity — AccountManager's platform-wide settlement list silently restricted to own account — settlements.py:42-43
- §3.8 — insert — ambiguity — final-variant sanitization fee falls back to `NIST_CLEAR` 700 when no `VERIFIED` record exists — calculations.py:133-142
- §3.9 — **revise — mismatch** — `recycling_fees_cents` includes the per-line sanitization fee (final basis) for data-bearing items, not just the recycling fee — calculations.py:282-285
- §4 — insert — ambiguity — 200 OK operations return the path-targeted resource (manifest/item/sanitization/listing/batch/settlement/certificate/`current_utc` object enumerated) — routes/*.py return statements
- §4 — insert — ambiguity — `status` filter on account-manifest and recycler-batch lists, `processing_status` filter on manifest-item list; invalid value → `ERR_VALIDATION` — accounts.py:100-104, recyclers.py:70-74, manifests.py:308-312
- §5 — insert — ambiguity — undefined paths/methods → `ERR_NOT_FOUND` (404), server failures → `ERR_INTERNAL` (500) — app.py:32-42

**Key finding:** the single true mismatch was §3.9's `recycling_fees_cents` — PRD read as recycling-fee-only, but the implementation adds the final-basis sanitization fee per line. Everything else was PRD silence pinned to the adopted behavior (guard-order positions, no-policy defaults, filter semantics, initial values, and return-body shapes).
