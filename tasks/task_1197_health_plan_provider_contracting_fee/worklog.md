# Worklog — task_1197_health_plan_provider_contracting_fee

## Step 1: Create Task Directory — 2026-08-11T17:49:00.000Z

Pre-assigned by orchestrator invocation: `tasks/task_1197_health_plan_provider_contracting_fee/` and its `workspace/` subdirectory already existed (verified on disk). No auto-index scan performed; treating Step 1 as done per instructions.

## Step 2: Generate Scaffold — 2026-08-11T18:35:00.000Z

Scaffold generation complete. All three files are in `/home/ubuntu/github/CodingPRD/tasks/task_1197_health_plan_provider_contracting_fee/`, and `scaffold_lint.py` reports **VERDICT: clean lint** (1,119 calls scanned across both design files, all FKs reverse-reachable).

## Counts (harder-than-expert calibration)

| Surface | This task | Expert band |
|---|---|---|
| Entities | **16** (Provider, Network, MedicareBenchmark, RateParityRule, Contract, ContractVersion, FeeScheduleEntry, CarveOut, SimulationBatch, SimulationClaim, PaidClaimSnapshot, RetroAdjustmentRun, RetroAdjustment, TerminationNotice, ContinuityOfCareCase, AuditEvent) | 10–15 |
| Endpoints | **78** | 20–32 |
| Error codes | **47** | 18–30 |
| State machines | **10** (Contract has 13 transitions incl. two cycles: negotiation loop + amendment re-entry from ACTIVE) | 4+ |
| Calculations | **10** | 3+ |
| Validations | **47 rows across 11 priority layers** (schema → auth → role → ownership → existence → state/OCC → safety → temporal → constraint → referential → fiscal) | — |
| Difficulty instances | **18** (9 rules × 2, all with full structured setup/trigger chains) | ≥18 |
| Corner instances | **57 active + 14 excluded-because stubs** across all 9 taxonomy sections | — |
| Concurrency | 2 OCC rules on Contract.version (version-create, notice-create), both 412 | — |

## Rule-differentiation highlights
- **R1**: escalator compounding (Contract domain, ANNIVERSARY vs CALENDAR → 10000 vs 10300) vs benchmark lookup mode (FeeScheduleEntry domain, STRICT vs PROVISIONAL).
- **R2**: mode (a) CASE_RATE outlier (strictly-greater branch + nested min cap, tested at 4 boundary points) vs mode (b) pinned round-per-line-then-sum (24003 vs 24002 — literals executed in Python during authoring).
- **R4**: go-live cascade depth 3 (Contract→Version EFFECTIVE→retro run CREATED) vs termination cascade depth 2 (Notice→Contract TERMINATED→conditional CoC/batch cascades).
- **R8**: half-open version windows (equal dates collide, distinct never) vs closed carve-out windows where *adjacency* collides.
- **R9**: money-ledger conservation (compute+void → paid ledger unchanged at 25000) vs claim-count partition conservation (price+reopen).

## Design adjudications
1. **Added `ACTIVE → IN_CONFIGURATION` transition** on Contract — without it, the amendment/retro flow (core scenario element) was unreachable after first go-live.
2. **Carve-out wildcard `"*"` category** — without it, the same-category closed-window conflict rule made `priority_rank` tie-breaking unreachable; wildcard makes multi-match possible.
3. **Batch creation gated on version VALIDATED/EFFECTIVE** (not DRAFT) so configuration testing follows fee-schedule lock, matching the scenario's "configuration testing before go-live" order.
4. **Logical clock default `2026-05-01T00:00:00Z`** declared on `/_clock/set_current_utc`; notice-finalize time gating uses it (one corner instance asserts rejection under the default clock).
5. **Segregation of duties** on sign (signer ≠ submitter) plus entity-backed `ProviderRep` with ownership-scoped reads.
6. A pinned-literal bug was caught during self-audit (10001×3333 bps = 3333.3333, no rounding divergence) and fixed to 10001×8000 bps = 8000.8 → 8001/line, 24003 vs 24002 — verified by executing the formula.

## Step 3: Copy Shared Files — 2026-08-11T18:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1197_health_plan_provider_contracting_fee/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T18:55:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1197_health_plan_provider_contracting_fee/workspace/PRD.md` (382 lines). The two forbidden design files and all sibling task directories were never opened.

## Section inventory
- **§1 Introduction** — 2 paragraphs (business context + system scope)
- **§2 Global Specifications** — 2.1 RBAC (all 6 roles with identity translations; the 8 ProviderRep ownership-scoped reads enumerated), 2.2 API Response Structure (verbatim block, anchors confirmed byte-identical), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties & Audit Trail (incl. AuditEvent carrying only `id`/`created_at` — no `updated_at`/`version`), 2.5 Monetary Precision/Basis Points/Rounding Order (integer cents, ÷10000, round-half-up, per-line-then-sum pinned, integer-step escalator compounding, floor-division parity ratio), 2.6 Window Semantics & Logical Clock (half-open version windows vs closed-with-adjacency carve-out windows vs half-open retro windows; clock default 2026-05-01T00:00:00Z), 2.7 OCC (both guarded creates, `expected_contract_version`, `ERR_STALE_VERSION`/412, stale-read framing only), 2.8 Cascade doctrine, 2.9 Nested retrieval (all 15 NOT_FOUND ids), 2.10 Validation evaluation order (11 tiers)
- **§3 Business Logic** — 9 subsections: 3.1 reference data, 3.2 provider onboarding/contract drafting, 3.3 negotiation & segregated signature, 3.4 versions/entries/benchmark mapping/escalator, 3.5 carve-outs, 3.6 simulation testing & claim pricing, 3.7 go-live & parity, 3.8 paid-claim ledger & retro settlement, 3.9 termination & continuity of care
- **§4 Endpoint table** — 78 rows matching the scaffold exactly (4 columns only)
- **§5 Error catalogue** — 47 rows (2 columns only)

## Coverage audit
- **Contract 1 (fields):** 99/99 entity fields, 53/53 endpoint input/query identifiers present in backticks — PASS
- **Contract 2 (rules):** all 53 transitions across 10 state machines expressed with preconditions + side effects + all 30 audit event types; all 10 calculations rendered as precise prose (STRICT/PROVISIONAL resolution, per-type base rates, ANNIVERSARY/CALENDAR step counting with the scaffold's 2026-07-01/2027-06-15 worked divergence, carve-out selection with wildcard/priority/created_at tiebreak, case-rate outlier with strict 300% comparison and 80% share capped at billed, half-open retro sweep with UNDERPAID/OVERPAID/zero handling and run totals, 7500-bps >= scoring, floor-division parity ratio with strict-greater violation, 90-day CoC cap, 90-day notice floor, closed+adjacency conflict); both OCC rules fully expressed; all 47 validations with priority ordering (global 11-tier order in §2.10 plus per-endpoint check sequences in §3); all endpoint `applies_to` scopes enumerated — PASS
- **Contract 3 (§3 path purity):** 551 backtick tokens scanned, 0 path/method violations — PASS
- All enum values (68) and all 47 error ids verified present in prose

## Deliberately resolved ambiguities
1. **Benchmark mapping for flat-rate entries:** the FeeScheduleEntry machine's map-benchmark preconditions/side effects are unconditional, so the PRD states resolution runs for every entry type, with `medicare_benchmark_id`/`resolved_benchmark_cents` always captured but `computed_rate_cents` for FLAT_RATE/PER_DIEM/CASE_RATE taken from `flat_rate_cents`.
2. **Rate parity projection date:** both sides of a ratio are escalator-projected at the *activating* version's `effective_date` (per the scaffold's `rate_x` definition), stated explicitly.
3. **Unspecified error mappings left unpinned:** map-benchmark against a post-DRAFT/LOADED/REJECTED version, notice issue against a non-ACTIVE contract, parity-rule same-LOB/duplicate-pair rejections, and tin/npi uniqueness are stated as rules without inventing error ids the scaffold does not nominate.
4. **Retro EXCLUDE carve-outs:** stated verbatim from the sweep rule — an EXCLUDE selection does not exclude the snapshot; it prices at the escalator-projected entry rate.

## Step 5: Generate Unit Tests — 2026-08-11T19:20:00.000Z

## Summary

**Files written**

- `test_helpers/` — 9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`
- `test_suite/` — 12 files: `conftest.py` + 11 test files (`test_01`…`test_11`)

**Test counts**

- **98 test functions** across 11 test files
- **9 helper modules** with 70+ fixture/factory/assertion functions

**Instance coverage**

- **Queue A (Difficulty)**: 18/18 instances translated, each with ≥ 2 tests (one instance has 3). Total difficulty-tagged tests: 37.
- **Queue B (Corner)**: 57/57 non-stub instances translated, each with ≥ 1 test. Total corner-tagged tests: 61.
- **Stubs (`excluded_because:`)**: 14 stubs correctly not translated (their `difficulty_instance` cross-references all resolve to real queue-A instances that own the assertions).

**Skipped instances**: 0. Every non-stub instance passed the PRD-first two-condition filter; no instances were dropped as PRD-silent or non-uniquely-derivable.

**Design-tag audit**: All 98 test functions carry exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim from the source yaml `name:` field. A programmatic audit confirmed all tags resolve to real instances and that tag count equals test count.

**PRD-citation audit**: Every test docstring includes verbatim PRD §-prefixed quotations. A grep-based check confirmed every quoted citation contains a distinctive ≥8-word contiguous substring that matches PRD.md (after whitespace normalization); one ellipsis-broken citation was rewritten and re-verified.

**Style**: No "scaffold" mentions in generated code; comments reference only PRD sections.

## Step 6: Generate Implementation — 2026-08-11T19:40:00.000Z

Implementation complete and verified. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1197_health_plan_provider_contracting_fee/workspace/implementation/`:

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, envelope error handlers (ApiError/404/405/500), `app.run(host="0.0.0.0", port=int($PORT or 10000))`
- `store.py` — 16 in-memory dict collections (all start empty, no seeding), strictly-monotonic ISO-8601-ms timestamps, logical clock (default `2026-05-01T00:00:00Z`, set-only), `stamp_new`/`touch` (updated_at refresh + version increment), audit-event appends (occurred_at from logical clock, no `updated_at`/`version` on AuditEvent)
- `errors.py`, `envelope.py` — ApiError; success envelope `{meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}` and error envelope `{meta, response_type:"error", data{error_id, message}}`; pagination limit default 10 / min 1 / max 100, offset default 0, lists sorted by created_at asc
- `security.py` — X-User-ID/X-User-Role auth (401), per-endpoint role lists (403), ProviderRep ownership scoping (403) on exactly the 8 PRD-enumerated reads
- `bodycheck.py` — tier-1 request conformance: required/conditionally-required fields, strict types (bool ≠ int), enum sets, YYYY-MM-DD/ISO-8601 validation, undeclared-field rejection — all evaluated before auth
- `pricing.py` — all 10 calculations: benchmark resolution (STRICT/PROVISIONAL), entry rate computation, escalator projection (ANNIVERSARY vs CALENDAR, integer round-half-up compounding per step), claim line pricing (carve-out selection with `*` wildcard + priority_rank/created_at ranking, EXCLUDE/FLAT/PCT overrides, PER_DIEM LOS, CASE_RATE outlier with strict `billed*10000 > 30000*base` compare and min-with-billed cap, per-line rounding), retro repricing sweep (half-open window, service_date/created_at order, EXCLUDE falls back to entry rate), simulation scoring (7500 bps, `>=` boundary passes), parity band evaluation (floor-division ratio, `>` violates), CoC coverage window, notice period (90 days), carve-out closed+adjacency window conflict
- `views_*.py` (10 blueprint modules) — all resource groups: reference data + clock, providers, contracts (lifecycle, OCC-guarded version/notice creation, paid claims, audit list), versions (load/validate/reload cycle, entry/carve-out/batch creation), entries (map-benchmark), carve-outs, simulation (price/score/reopen compensation), retro (compute/finalize/void, approve/reject/settle with FINALIZED→SETTLED bubble-up), termination (issue/finalize/rescind cascades, CoC case lifecycle), audit

## Endpoints

All **78** (method, path) pairs from SCAFFOLD.yaml implemented; a programmatic diff of `app.url_map` against the scaffold's endpoint table confirms exact equality (78/78, no missing, no extra — Flask's default `/static` route was disabled). Orchestrator independently re-verified after Step 6: 78 scaffold endpoints vs 78 Flask routes, normalized path params, 0 missing / 0 extra.

## Boot

`start.sh`: `set -euo pipefail`, cds to its own dir, installs requirements only if `import flask` fails (guarded for per-test-server reboots), then `exec python3 app.py` in the foreground. Verified booting via `bash start.sh` to HTTP-ready in ~1 second.

## Checks

- `python3 -m py_compile` passes on all 18 `.py` files.
- Two custom end-to-end suites (≈140 assertions) run against fresh `start.sh` boots both pass 100%: full lifecycle (network→benchmark→provider→contract→negotiation/SoD/counter-offer→sign→version OCC/temporal/uniqueness ordering→entry floor/duplicate/resolvable→map STRICT/PROVISIONAL→load/validate/reject→testing gate→batch price/score/reopen→mark-ready→go-live cascade with VERSION_EFFECTIVE/SUPERSEDED/retro-run spawn→paid claims→retro compute/finalize/settle bubble-up and void compensation→termination notice/issue/finalize with clock gate and cascades→rescind compensation→CoC window/expire→audit trail contents→ProviderRep ownership→pagination→400-before-auth ordering), plus edge math (escalator mode divergence on the PRD's exact example, case-rate outlier boundaries, 75%-exact score boundary, parity violation 422 leaving the contract READY_FOR_GO_LIVE).

One spec subtlety confirmed during testing: map-benchmark runs benchmark resolution for **all** rate types (flat-rate entries also require a PUBLISHED benchmark for code+locality), while `ERR_BENCHMARK_UNRESOLVABLE` at entry creation applies only to PERCENT_OF_MEDICARE entries — both implemented as the PRD states.

## Step 7: Run Tests and Iterate — 2026-08-11T19:44:00.000Z

Clean 8-round parallel sweep achieved: **all 8 rounds, 98/98 passed each**.

## Summary

- **Iterations run**: 3 sweeps (iteration 1: collection failure; iteration 2: 7 consistent failures; iteration 3: clean 8×98/98).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`** (1 file, collection repair):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1197_health_plan_provider_contracting_fee/test_suite/test_02_claim_pricing_formulas.py` — removed import of nonexistent helper `setup_contract_in_configuration` and its dead guarded call (leftover from generation; blocked all 98 tests at collection); added `create_published_benchmark(hcpcs_code="J9999")` precondition in `_version_with_case_rate_entry` — PRD §3.4 requires a PUBLISHED benchmark matching code+locality+year at map-benchmark for every rate type.

- **Fixes applied to `test_helpers/`**:
  - `factories.py` `create_carve_out_payload` — payload keys now shaped by final `override_type` (FLAT_RATE→`override_flat_cents`, PCT_OF_MEDICARE→`override_pct_bps`, EXCLUDE→neither, explicit caller keys preserved). PRD §3.5: "an exclusion carries neither" — the factory previously injected `override_flat_cents` into EXCLUDE payloads, tripping the PRD-faithful 400.
  - `fixtures.py` `setup_contract_in_configuration_with_mapped_version` — new optional `carve_outs` param created while the version is still DRAFT (before load/validate). PRD §3.5 accepts carve-outs only in DRAFT/LOADED/REJECTED; three tests were creating them on a VALIDATED version.

- **Fixes applied to tests in `test_10_calculations_corner.py`**: three carve-out tests (`test_flat_carve_out_overrides_entry_rate`, `test_lower_priority_rank_wins_over_specific`, `test_exclude_carve_out_excluded_and_not_counted`) moved carve-out creation into the fixture's pre-validation window; `test_per_diem_multiplies_los_days` now publishes a DRG1 benchmark before mapping (same PRD §3.4 resolution requirement).

- **Fixes applied to `implementation/`**: none — every failure traced to test-artifact bugs; the implementation was PRD-faithful in all seven cases (verified against verbatim PRD quotes for the map-benchmark resolution scope, carve-out version-state gate, and conditional override payload shape).

## Step 8: Finalize PRD — 2026-08-11T19:50:00.000Z

`PRD_FINALIZED.md` is written with exactly one inline revision. Summary:

**Line counts / delta**
- `PRD.md`: 382 lines; `PRD_FINALIZED.md`: 382 lines — 0.0% delta (single inline sentence extension, no lines added or removed).

**Changes**
- §3.5 — revise — extended the carve-out payload parenthetical: "an exclusion carries neither — supplying either override payload field on an exclusion is a request-conformance violation, rejected with `ERR_INVALID_REQUEST` (HTTP 400)" — `implementation/views_versions.py:190-192` (`forbid_present` on `override_flat_cents`/`override_pct_bps` for `EXCLUDE`), `implementation/bodycheck.py:121-123`.

**Step-7 items with no edit (and why)**
- test_02 dead-import removal: pure test-collection bug, no behavior.
- `create_published_benchmark` preconditions (test_02 `_version_with_case_rate_entry`, test_10 `test_per_diem_multiplies_los_days`): PRD §3.4's mapping paragraph already states one uniform resolution algorithm for every rate type — PUBLISHED rows matching code+locality, year filter per lookup mode, empty candidate set → `ERR_BENCHMARK_UNPUBLISHED` 422 — with no rate-type branch; §2.10 tier 10 lists the check generically. Matches `implementation/views_entries.py:68` + `pricing.py:33-51` verbatim; kept verbatim.
- Fixture `carve_outs` pre-validation window (fixtures.py + three test_10 moves): PRD §3.5 already pins verbatim "accepted only while the version is in `DRAFT`, `LOADED`, or `REJECTED`; otherwise creation fails with `ERR_VERSION_INVALID_STATE`" — matches `views_versions.py:23,196`. Pure fixture bug.

**Per-edit pre-edit search log**
- Edit 1 (§3.5 EXCLUDE payload rejection):
  - (a) Subject: carve-out override-payload shape validation keyed by `override_type`.
  - (b) Enumerated impl paths: `views_versions.py:174-216` (the only carve-out write endpoint; FLAT_RATE requires `override_flat_cents` but *accepts and stores* a supplied `override_pct_bps`, and vice versa — only EXCLUDE forbids), `views_versions.py:219-225` (list, read-only), `views_carveouts.py:12-16` (get, read-only), `pricing.py:98-109` `select_carve_out` (read-only), `pricing.py:122-158` `price_claim_line` and `pricing.py:180-217` `retro_sweep` (consume `override_flat_cents` only on the FLAT_RATE branch, `override_pct_bps` only on PCT_OF_MEDICARE; EXCLUDE never reads payloads). Verified no carve-out update endpoint exists.
  - (c) Wording adjustment: scoped the rejection to EXCLUDE alone. An earlier generalization ("non-matching payload fields are rejected") was rejected because it would mis-describe the FLAT_RATE/PCT_OF_MEDICARE accept-and-store paths at `views_versions.py:186-189,209-210`. Phrased with §2.10 tier-1 vocabulary ("request-conformance violation") without amending §2.10, keeping the patch minimal and consistent with every enumerated path.

## Step 9: Complete PRD — 2026-08-11T20:02:00.000Z

All edits are in place and well-formed. The work is complete.

## Summary

**Deliverable**: `/home/ubuntu/github/CodingPRD/tasks/task_1197_health_plan_provider_contracting_fee/workspace/PRD_COMPLETED.md`

**Source vs. output**: `PRD_FINALIZED.md` (382 lines / 64,569 chars) → `PRD_COMPLETED.md` (387 lines / 68,429 chars); char-delta **+3,860**, +5 lines (all from new catalogue rows; every other change is an in-paragraph insert/revision).

**Counts**: 22 ambiguity-pins in prose + 5 error-catalogue row inserts (27 total ambiguity fixes); 2 mismatch-revisions (both in §2.8).

### Changes (one bullet each)

- §2.1 — insert — ambiguity — ownership comparison presupposes a resolved resource; unresolvable id yields 404 before ownership — implementation/views_providers.py:62-63
- §2.2 — insert — ambiguity — cascade-triggering transitions return the path-addressed primary resource (e.g., notice issue returns the notice) — implementation/views_termination.py:72
- §2.3 — insert — ambiguity — non-integer limit/offset falls back to defaults, out-of-range clamped; total_count = filtered size pre-pagination; has_more formula; filters exact-match with empty page on no match — implementation/envelope.py:41-71
- §2.4 — insert — ambiguity — `version` counter starts at 1 on creation — implementation/store.py:81-88
- §2.6 — revise — ambiguity — clock-set applies the instant unconditionally, backward allowed — implementation/views_reference.py:204-210
- §2.7 — insert — ambiguity — OCC guard rejects any inequality in either direction — implementation/views_contracts.py:267-271, 380-384
- §2.8 — revise — **mismatch** — version increments on every mutation per §2.4, not "only where the workflow sections say so" (impl `touch()` bumps on all mutations, e.g. claim-add bumps batch) — implementation/store.py:91-94, views_simulation.py:65-66
- §2.8 — revise — **mismatch** — cascade-audit doctrine: cascades append the events §3 records; batch reopen records none (impl appends no audit on reopen) — implementation/views_simulation.py:133-152
- §2.9 — insert — ambiguity — routing-level errors: ERR_NOT_FOUND (404), ERR_METHOD_NOT_ALLOWED (405), ERR_INTERNAL (500) — implementation/app.py:40-52
- §2.10 tier 4 — insert — ambiguity — ownership tier evaluated against resolved resource; unresolvable id falls through to tier 5 — implementation/views_providers.py:62-63
- §2.10 tier 9 — insert — ambiguity — added ERR_DUPLICATE_PROVIDER and ERR_DUPLICATE_PARITY_RULE to the uniqueness tier — implementation/views_providers.py:30-35, views_reference.py:168-176
- §3.1 — insert — ambiguity — retiring an already-RETIRED network is an idempotent 200 no-op — implementation/views_reference.py:58-67
- §3.1 — insert — ambiguity — same-LOB parity rule is ERR_INVALID_REQUEST (400); second ACTIVE rule for an unordered pair is ERR_DUPLICATE_PARITY_RULE (409) — implementation/views_reference.py:161-176
- §3.2 — insert — ambiguity — duplicate tin/npi rejected with ERR_DUPLICATE_PROVIDER (409) — implementation/views_providers.py:30-35
- §3.3 — insert — ambiguity — counter-offer `note` accepted but not persisted — implementation/views_contracts.py:79-90
- §3.4 — insert — ambiguity — non-matching entry rate payload field accepted, stored, never consulted — implementation/views_versions.py:100-112, 143-155
- §3.4 — insert — ambiguity — load from states other than DRAFT/REJECTED fails ERR_VERSION_INVALID_STATE — implementation/views_versions.py:49-67
- §3.5 — insert — ambiguity — non-required override payload on FLAT_RATE/PCT_OF_MEDICARE carve-outs accepted and stored unused; reversed windows accepted but match nothing — implementation/views_versions.py:186-192, pricing.py:98-109
- §3.6 — insert — ambiguity — PCT_OF_MEDICARE carve-out with no matching/resolved entry yields MISMATCH with null price — implementation/pricing.py:131-137
- §3.6 — insert — ambiguity — reopen appends no audit event — implementation/views_simulation.py:133-152
- §3.7 — insert — ambiguity — multiple VALIDATED versions: latest effective_date activates (tie → later created_at); none VALIDATED → ERR_CONTRACT_INVALID_STATE — implementation/views_contracts.py:208-213
- §3.7 — insert — ambiguity — parity zero-rate guard: non-positive lesser rate + positive greater = automatic violation; both non-positive = skipped — implementation/pricing.py:285-291
- §3.8 — insert — ambiguity — settle consults only the adjustment's own state, not the parent run's — implementation/views_retro.py:194-211
- §3.9 — insert — ambiguity — notice issue against non-ACTIVE contract fails ERR_CONTRACT_INVALID_STATE (409) — implementation/views_termination.py:57-62
- §3.9 — insert — ambiguity — case notify/activate-coverage against wrong parent-notice state fails ERR_CASE_INVALID_STATE — implementation/views_termination.py:199-201, 215-217
- §5 — insert — ambiguity (×5 rows) — catalogue rows for ERR_DUPLICATE_PROVIDER (409), ERR_DUPLICATE_PARITY_RULE (409), ERR_NOT_FOUND (404), ERR_METHOD_NOT_ALLOWED (405), ERR_INTERNAL (500) — implementation/views_providers.py:33, views_reference.py:174, app.py:42/46/52

**Key findings**: The finalized PRD was already tightly aligned with implementation; all endpoint paths, role lists, state machines, calculation formulas (rhu rounding, escalator modes, outlier branch, scoring threshold, parity integer division), check orderings, and window semantics matched exactly. The genuine defects were confined to §2.8's version-increment sentence and its cascade-audit blanket claim (contradicted by audit-less batch reopen), plus five error identifiers the implementation emits that the catalogue omitted entirely.
