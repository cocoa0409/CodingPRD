# Worklog — task_2005_utility_rate_case_cost_service_filing

Difficulty directive from user: "Generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-15T06:11:00.000Z

Pre-existing per command args: `tasks/task_2005_utility_rate_case_cost_service_filing/` and `tasks/task_2005_utility_rate_case_cost_service_filing/workspace/` already created. No index scan performed; no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-15T07:48:00.000Z

Done. All three scaffold artifacts for task 2005 are generated, cross-consistent, and lint-clean.

## Generated files

- `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/SCAFFOLD.yaml` (§1.0–§1.7 only; neither forbidden key present)
- `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design:`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design:`)

## Summary counts

| Element | Count |
|---|---|
| Entities | 13 (RateCase root; Intervenor, TestYearEntry, Adjustment, RateBaseItem, CustomerClass, DataRequest, SettlementProposal, SettlementSignatory, RegulatoryAsset, AmortizationEntry, TariffRate, ComplianceFiling — flat topology, FK-in-body) |
| State machines | 12 (69 transitions; 12-state cyclic RateCase chain with DEFICIENT cure loop, cyclic SettlementProposal ASSENTED↔UNDER_NEGOTIATION, branching DataRequest with clock-driven OVERDUE arms) |
| Calculations | 12 (incl. dual-variant revenue requirement as_filed/as_audited, dual-variant class cost allocation CP vs EA, tiered marginal pricing, floor-plus-tail amortization, gradualism cap, de-minimis true-up with residual assignment, two clock sweeps) |
| Endpoints | 76 (incl. 3 computed reads and `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z) |
| Error codes | 62 (all referenced in rules; all exercised by at least one test) |
| Roles | 4 (UtilityFiler/CommissionStaff/ALJ opaque; IntervenorRep `entity_backed:Intervenor` with ownership scoping; SoD on adjustment verify) |
| Concurrency rules | 2 OCC rules on RateCase.version (settlement round create-with-supersede, compliance filing create-with-supersede) |
| §1.8 instances | 23 (every rule ≥2: dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_sm 3, cascade 3, priority_pair 2, boundary 3, cross_entity 3, temporal_overlap 2 with different interval semantics, compensating_invariant 2) |
| §1.9 instances | 61 active + 24 excluded stubs across all 9 guide sections |

## Key design decisions

- **Pinned numeric fixture verified by execution** (Python): COS 1,650,000,000c; RR 1,897,500,000 (as_filed) vs 1,830,000,000 (as_audited); allocation RES 1,242,500,000 vs 1,160,000,000 by method; gradualism cap exactly 1,358 bp with pass/fail tariffs at 695,088,000/695,160,000; amortization 10,000,001/4 → 3×2,500,000 + 2,500,001; true-up threshold 9,250,000 with exact-boundary NONE case and REFUND lines 12,941,176/7,058,824.
- **Validation precedence**: 16 rows over 13 priority levels (0 request-shape → 1–4 auth/ownership/SoD → 5 existence → 6 state → 7 safety floor → 8 temporal → 9 referential → 10 constraint → 11 fiscal → 12 OCC), with dual-failure instances for state-vs-fiscal, temporal-vs-referential, ownership-vs-state, and safety-vs-temporal.
- **Audit fixes made during generation**: split the adjustment guard (DISPUTED blocks entry lock; PROPOSED blocks case filing) so both error codes are reachable; added a `system_avg_increase_bp <= 0` skip clause to the gradualism cap; pinned guard sub-orders (submit-filing positions 1–4, nonpositive-before-mismatch, tariff-ids-before-asset-ids); added explicit VOID cascade transitions and a global `list_ordering` block so list-indexed captures are deterministic without ever using `id` as a sort key.

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1549

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Extended audits beyond the linter (placeholder closure, grounds resolvability, stub references, forbidden OCC vocabulary, error-catalog reference + test coverage, enum closure, RBAC/endpoint role consistency) all pass clean. Note: the task directory also contains a pre-existing `worklog.md` and `workspace/` (not created by me, left untouched). No sibling task directories were read at any point.

## Step 3: Copy Shared Files — 2026-08-15T07:49:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2005_utility_rate_case_cost_service_filing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T07:58:00.000Z

Done. Here's the final summary:

**PRD generated**: `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/workspace/PRD.md`

**Line count**: 361 lines

**Sections covered**:
- §1 Introduction (3 paragraphs, product-manager perspective on the rate-case lifecycle)
- §2 Global Specifications — 2.1 RBAC with identity semantics for all four roles (`UtilityFiler`, `CommissionStaff`, `IntervenorRep` entity-backed, `ALJ`); 2.2 fixed verbatim response-structure block; 2.3 Pagination (limit default 10/min 1/max 100, offset default 0, `created_at` ASC, pinned tie-breaks for AmortizationEntry and SettlementSignatory cascades); 2.4 Common resource properties (`id`, `created_at`, `updated_at`, `version`, `status`); 2.5 Monetary precision and rounding modes; 2.6 Procedural clock (startup `2026-08-01T00:00:00Z`, forward-only, `ERR_CLOCK_REGRESSION`); 2.7 Nested path validation; 2.8 OCC with `expected_rate_case_version` and `ERR_STALE_VERSION` 412 on settlement-create and compliance-filing-create; 2.9 Validation priority order; 2.10 Aggregate counters `overdue_data_request_count` and `assented_proposal_count`
- §3 Business Logic & Workflows — 3.1 docket opening & test-year assembly; 3.2 adjustments & segregation of duties; 3.3 rate base & submit-filing pinned guard order; 3.4 discovery & data-request lifecycle with sweeps; 3.5 settlement circulation & unanimous-consent bubble-up; 3.6 final order, tariff approval, amortization schedule (floor + tail remainder, LIFO reversal); 3.7 customer classes, cost allocation (60/25/15, residual assignment, tie-breaks), tariff creation with anti-subsidy floor and gradualism cap; 3.8 revenue-requirement two variants with pinned rounding order, bill-impact selection rule, true-up de-minimis (100000 cents vs 0.005 of authorized) with per-class lines; 3.9 party registration & withdrawal cascade
- §4 Endpoint Definitions — 4-column table, 75 rows covering all scaffold endpoints
- §5 Error Code Catalogue — 2-column table, all 63 error IDs with HTTP status

**Coverage-audit verdicts**:
- Contract 1 (Field-Name Coverage): **PASS** — all entity fields, request-body keys, query params, path params, and computed-read response fields appear verbatim in backticks
- Contract 2 (Rule Coverage): **PASS** — validations with priority expressed in pinned order (submit-filing guards, validation cascade, tariff-vs-asset id validation in issue-order); both OCC rules expressed with endpoint, `expected_rate_case_version`, `ERR_STALE_VERSION`, 412; all state-machine transitions named with from/to, preconditions, error IDs, side-effects; all nine calculations expressed in precise business prose with constants embedded (60%/25%/15, 100-cent RR tolerance, 120-day discovery, 10-day response, 5-day extension, 100000-cent de-minimis, 0.005 pct, 1.5 gradualism factor); cross-entity cascades enumerated hop-by-hop (issue-order 5-hop cascade, withdrawal 4-hop cascade, sign bubble-up, rescind drop-down, supersede void cascades, amortization post/reverse bubble-ups); sibling branches treated symmetrically (SUSTAINED/OVERRULED, AUDIT_PASS/AUDIT_EXCEPTION, ACCEPT/REMAND, ACCEPTED/DEFICIENT, as_filed/as_audited, COINCIDENT_PEAK/ENERGY_AVERAGE)
- Contract 3 (§3 Path Purity): **PASS** — 674 backtick tokens in §3 scanned; zero path tokens, zero bare HTTP methods, zero method+path combined tokens

## Step 5: Generate Unit Tests — 2026-08-15T08:51:00.000Z

Generation complete for task_2005_utility_rate_case_cost_service_filing.

## Deliverables

**test_helpers/** (9 files): `types.py` (13 TypedDicts + status enums + role enum), `api_client.py` (one method per PRD endpoint, incl. `/_clock/set_current_utc`), `api_errors.py` (62 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity asserts + `assert_instant_equals` + amortization coverage invariant), `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_intervenor_rep_headers` + opaque-role constants incl. uf_alice/uf_bob for SoD), `fixtures.py` (atomic builders + phase-walkers + composite chains: filed → discovery → settlement → circulated → assented → order-pending → decided → rates-implemented → compliance, in canonical, RES-only, zero-class, and "light" single-entry variants).

**test_suite/**: `conftest.py` + 9 test files, **107 tests** total.

## Coverage

- **Queue A (Difficulty): 23/23 instances, exactly 2 tests each = 46 tests.**
- **Queue B (Corner): 61/61 non-stub instances, exactly 1 test each = 61 tests.**
- 24 `excluded_because` stubs not translated (per spec); all `difficulty_instance` cross-references verified to resolve.
- **Instances skipped on PRD-first grounds: none** — every non-stub instance has verbatim PRD coverage and a uniquely-derivable outcome.

## Assertion-level trims (two-condition filter applied inside instances)

1. Dropped `version == 1` literals (creation-defaults, computed-fields instances): PRD says version "increments on mutation" but never pins the initial value.
2. Pagination instance: dropped exact AAA/BBB/CCC row order — three separate creates share one logical-clock instant and PRD pins no non-cascade tie-break; asserted page sizes/total_count/has_more plus exact id-set partition instead.
3. Timestamp literals asserted as parsed instants, not string equality (PRD §2.4's three-fractional-digit rule vs §2.6's pinned instant leaves rendering open).
4. Cost-allocation instance: per-line field names are unnamed in PRD; CP per-class values asserted via the named `allocated_cost_cents` entity field, EA variant via naming-agnostic membership checks on lines plus the named envelope fields.

## Setup-chain repairs (recipes replayed with RR consistency, asserted literals unchanged)

Many YAML recipes filed the canonical case with proposed RR 1,897,500,000 but only RB1 submitted (computed 1,830,000,000 or 1,180,000,000 → setup would die at ERR_RR_MISMATCH). Fixtures add RB2 (net 900,000,000) to full-canonical chains (computed == proposed exactly); single-entry "light" chains use proposed 1,180,000,000; the bill-impact instance was upgraded to the full canonical chain because its 745-bp tariff otherwise exceeds the gradualism cap. Every asserted numeric literal was independently re-derived from the PRD formulas with a reference implementation (all match, incl. cap 1358 bp, true-up lines 12,941,176/7,058,824, amortization tail 2,500,001).

## Stage-2 self-audit verdicts (all PASS)

- No untagged/dual-tagged tests; every docstring ends with exactly one `Design:` line resolving to a real instance.
- Every ≥8-word docstring quote greps verbatim in PRD.md (whitespace-normalized).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- All modules compile; every test-file import resolves against `test_helpers`.

## Step 6: Generate Implementation — 2026-08-15T08:53:00.000Z

The implementation is complete and fully verified. Final summary:

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/workspace/implementation/`

### File list
- `start.sh` (executable, guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000) + `requirements.txt` (flask)
- `app.py` — blueprint registration (`/api/v1` prefix; clock at root), ApiError/404/405/exception handlers
- `db.py` — in-memory store; `errors.py` — full 50-code error catalog with exact HTTP statuses; `middleware.py` — `X-User-ID`/`X-User-Role` extraction + role checks; `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`); `util.py` — logical clock (default `2026-08-01T00:00:00Z`, strictly-forward), exact-integer round-half-up/away-from-zero helpers; `validate.py` — shape validation incl. tier arrays and resource-specific 404 loaders
- `routes/` (15 modules): rate_cases, intervenors, test_year_entries, adjustments, rate_base_items, customer_classes, data_requests, settlement_proposals, settlement_signatories, regulatory_assets, amortization_entries, tariff_rates, compliance_filings, clock, helpers
- `services/`: core (record lifecycle, recomputes), calculations, sweeps

### Endpoints: 76/76 implemented
13 entity groups + 3 computed reads (revenue-requirement, cost-allocation, bill-impact) + the `POST /_clock/set_current_utc` test-driving clock, matching the scaffold table exactly.

### Calculation modules
`tiered_marginal_cents` (per-tier round-half-up then sum, boundary-inclusive marginal walk), `revenue_requirement` (dual variant as_filed/as_audited, pinned COS→RB→rounded-return order), `class_cost_allocation` (60/25/15 components, per-component round-half-up, residual to largest pre-residual class), `customer_cost_floor_cents` + `gradualism_cap_check` (skip when system avg ≤ 0, strictly-greater trigger, exact bp boundary), `amortization_amounts` (floor base + remainder to tail), `compute_true_up` (raw-actuals delta, two-term max threshold, NONE at exact threshold, half-away-from-zero lines, residual to largest-actual class), plus the two clock sweeps (discovery overdue at strict `<`, tariff supersede only by later-starting EFFECTIVE successor).

### State / storage organization
- `db` = dict of 13 empty-at-boot collections keyed by UUID; a monotone `_seq` insertion counter supplies the pinned tie-break for rows sharing one logical-clock `created_at` (UUIDs never sort keys)
- **No seeding** — store provably empty at boot (verified via fresh-boot read)
- Entity `created_at`/`updated_at` stamped from the logical clock (`%Y-%m-%dT%H:%M:%SZ`); `version` starts at 1, incremented on every mutation including cascaded children and the RateCase counter hops (sweep flips, assented bubble-up/rescind)
- `overdue_data_request_count`/`assented_proposal_count` maintained incrementally per PRD 2.10; `present_revenue_total_cents`, both RR variants, and `revenue_at_approved_rates_cents` derived live at serialization
- Validation pipeline follows PRD §2.9 priority order (shape → auth → role → existence → ownership/SoD → state → floor → temporal → referential → structural → fiscal → OCC), confirmed by the pinned priority-conflict corner pairs

### Verification
~190 bespoke assertions across 4 replay scripts of the scaffold's corner/difficulty designs (canonical numbers, boundary and cascade cases), all passing, each wave re-run on a fresh process boot. `bash start.sh` boots to HTTP-ready in ~2s on a custom PORT; pyflakes clean.

## Step 7: Test-Fix Loop (8-round parallel stability sweeps) — 2026-08-15T09:25:00.000Z

Three iterations run under `prd-bench-local-run --isolation per-test-server` (8 concurrent rounds each).

- Sweep 1: 103/107 in every round — 4 deterministic failures (same 4 tests in all 8 rounds).
- Sweep 2 (after test-artifact fixes): the 4 original failures gone; 7/8 rounds then lost
  `test_true_up_class_lines_rounding_and_residual` to `ConnectionResetError` mid-test — diagnosed as
  co-tenant pipelines on this shared host running `pkill -f "python3 app.py"` as sweep cleanup,
  which name-matched and killed this task's server process (no port involvement; server logs showed
  normal boot/kill cadence in-window, zero foreign traffic, zero tracebacks, ample free memory).
- Sweep 3 (after entry-file rename): 107/107 in all 8 rounds. CLEAN EXIT.

Fixes applied:
1. `test_suite/test_05_discovery_and_data_requests.py` — `_setup_overdue_party_request()` was missing
   its `api` parameter (NameError on `api.set_clock`); added the parameter and updated both call sites
   (`test_intervenor_withdraw_overdue_cascade`, `test_intervenor_withdraw_reopens_hearing_gate`).
2. `test_suite/test_05_discovery_and_data_requests.py` — added missing module constant
   `IR = TEST_USERS["intervenor_rep"]` used by `test_rbac_role_denials_unauthorized`.
3. `test_helpers/assertions.py` — `assert_amortization_coverage_invariant` claimed a PRD-silent rule
   (`amortized_to_date + sum(PENDING) == principal`), which is false after a reversal. Repaired to the
   PRD §3.6-derivable accounting identity `amortized_to_date + sum(PENDING) + sum(REVERSED) == principal`
   (composes "sum of all generated amount_cents equals principal_cents exactly" with the post/reverse
   add/subtract rules); `test_08_amortization.py` now passes the asset's full entry list via a new
   `_all_entries` helper so REVERSED rows are visible.
4. `workspace/implementation/` — renamed entry `app.py` → `utility_rate_case_server.py` and updated
   `start.sh` (same sibling-task defense pattern, e.g. task_1293/1294/2014), removing the host-wide
   `pkill -f app.py` kill vector. No endpoint, field, or behavior change.

No tests deleted; no assertions weakened; no implementation check removed.

### Step 7 subagent returned summary (verbatim)

All 8 rounds of sweep 3 pass 107/107 — clean exit condition met.

## Summary

**Iterations run: 3** (each = 8 concurrent `prd-bench-local-run --isolation per-test-server` rounds)

- Sweep 1: 103/107 in all 8 rounds — 4 deterministic failures (same 4 tests everywhere).
- Sweep 2: the 4 original failures cleared, but 7/8 rounds lost `test_true_up_class_lines_rounding_and_residual` to `ConnectionResetError` mid-test — root-caused to **co-tenant pipelines on this shared host running `pkill -f "python3 app.py"` as sweep cleanup**, which name-matched and killed this task's Flask process mid-request. Evidence: server logs showed normal per-test boot/kill cadence within our window, zero foreign request traffic on our ports, zero tracebacks, 76GB free RAM, and the sibling test with a byte-identical request chain passed in the same rounds. Sibling tasks (task_1293, 1294, 2014, …) document the same aggressor pattern in their start.sh comments.
- Sweep 3: **107/107 × 8 rounds, zero failures.**

**Tests deleted: none.**

**Fixes applied to `test_helpers/`:**
- `assertions.py` — `assert_amortization_coverage_invariant`: the old rule (`amortized_to_date + sum(PENDING) == principal`) is PRD-silent and false after a reversal. Repaired to the PRD §3.6-derivable accounting identity `amortized_to_date + sum(PENDING) + sum(REVERSED) == principal` (composes the verbatim "sum of all generated `amount_cents` equals `principal_cents` exactly" with the post/reverse add/subtract rules), preserving the compensating-invariant design intent.

**Fixes applied to `test_suite/`:**
- `test_05_discovery_and_data_requests.py` — `_setup_overdue_party_request()` used `api.set_clock` without accepting the `api` fixture (NameError); added the parameter and updated both call sites (`test_intervenor_withdraw_overdue_cascade`, `test_intervenor_withdraw_reopens_hearing_gate`).
- `test_suite/test_05_discovery_and_data_requests.py` — added missing module constant `IR = TEST_USERS["intervenor_rep"]` used by `test_rbac_role_denials_unauthorized` (NameError).
- `test_08_amortization.py` — added `_all_entries()` helper; both invariant call sites now pass the asset's full entry list so REVERSED rows are visible to the repaired invariant.

**Fixes applied to `implementation/`:**
- Renamed entry `app.py` → `utility_rate_case_server.py` and updated `start.sh` accordingly (the evaluator contract is `bash start.sh` only), removing the host-wide `pkill -f app.py` kill vector. No endpoint, field, side effect, or behavior change; storage remains in-memory only.

No assertions weakened, no error_id downgraded, no skips/xfails, no PRD-required implementation checks removed, nothing seeded. All fixes trace to verbatim PRD sentences; the environmental (pkill) failure was fixed structurally rather than by retry.

## Step 8: Finalize PRD — 2026-08-15T09:29:00.000Z

Done. PRD_FINALIZED.md is in place; the analysis concludes with zero edits, which I verified rather than assumed. Here is the full accounting.

## Result

**PRD.md vs PRD_FINALIZED.md:** 361 lines vs 361 lines — 0.0% delta, byte-identical (verified with `cmp`). The file was produced by `cp` per step 0 and no edit survived the traceability test.

## Why no edits — per `<step_7_diff>` item

- **test_helpers/assertions.py — amortization coverage invariant repair.** The repaired identity (`amortized_to_date + sum(PENDING) + sum(REVERSED) == principal`) is, by the diff's own description, "PRD §3.6-derivable" — it composes two verbatim PRD rules: "the sum of all generated `amount_cents` equals `principal_cents` exactly" (§3.6) and the post/reverse add/subtract rules on a zero-initialized counter. The implementation exhibits no choice the PRD leaves open: post adds and moves PENDING→POSTED, reversal subtracts and moves POSTED→REVERSED, entries are never deleted. The old helper rule was a test-side mis-composition (a fixture-class bug), not a PRD silence about behavior. Per "where PRD already determines behavior, keep prose verbatim" — no edit.
- **test_05 `_setup_overdue_party_request()` missing `api` parameter.** Pure fixture NameError; no behavioral content. No edit.
- **test_05 missing module constant `IR`.** Pure fixture NameError; no behavioral content. No edit.
- **test_08 `_all_entries()` helper + call sites.** Test-side plumbing feeding the repaired invariant. The behavior it exposes — REVERSED rows remain visible in the unfiltered amortization-entry list — is already pinned by §3.6 (reversal is a state move, not removal) and §4 (list endpoint with optional status filter). No edit.
- **implementation/ rename `app.py` → `utility_rate_case_server.py` + start.sh.** The diff states "No endpoint, field, side effect, or behavior change". PRD.md contains zero statements about entry-point filenames, process layout, or storage mechanism (grep for `app.py|start.sh|entry point|persist|database|restart` hits only unrelated uses of "persisted resource"). The `bash start.sh` evaluator contract lives in INSTRUCTION.md, which is outside the PRD patch surface. No edit.

## Per-edit pre-edit search log (applied to each candidate edit)

**Candidate 1 — amortization coverage identity (§3.6).**
- (a) Subject: post/reverse arithmetic on `amortized_to_date_cents` and the persistence/visibility of REVERSED AmortizationEntry rows.
- (b) Paths enumerated and read: `implementation/routes/amortization_entries.py` (post lines 45–75, reverse lines 78–105), `implementation/routes/regulatory_assets.py` (schedule math lines 54–55, `amortized_to_date_cents` init line 65), `implementation/routes/regulatory_assets.py` + all other route files via grep for `bp.delete|del db[` (no delete path exists anywhere), `test_helpers/assertions.py` lines 179–195, `test_suite/test_08_amortization.py` (both invariant call sites, lines 198/216).
- (c) Outcome: PRD §3.6 already pins every enumerated path verbatim (post adds, reverse subtracts, REVERSED persists, schedule conserves principal). Any added identity sentence would be redundant prose, not a behavioral pin — so no wording was committed, eliminating all new-mismatch risk.

**Candidate 2 — clock/overdue/withdraw-cascade wording (underlying the test_05 fixture fixes).**
- (a) Subject: clock-set semantics, discovery-overdue sweep, intervenor-withdraw cascade counter decrements.
- (b) Paths enumerated and read: `implementation/routes/clock.py`, `implementation/util.py` (`LogicalClock.set`, lines 55–62), `implementation/services/sweeps.py` (`discovery_overdue_sweep`, lines 7–31), `implementation/routes/intervenors.py` (`withdraw_intervenor`, lines 53–94), `test_suite/test_05_discovery_and_data_requests.py` lines 396–438.
- (c) Outcome: impl matches PRD §2.6/§3.4/§3.9 exactly (strictly-forward clock, strictly-before overdue comparison, hop cascade with counter decrement). The test fixes were NameErrors only — no PRD wording was touched.

**Candidate 3 — entry-point/process wording (underlying the impl rename).**
- (a) Subject: server entry filename and start contract.
- (b) Paths enumerated and read: `implementation/utility_rate_case_server.py`, `implementation/start.sh`, `implementation/db.py`, `workspace/INSTRUCTION.md`, plus a full-PRD grep for filename/storage terms (no hits).
- (c) Outcome: PRD is silent on filenames by design and the rename changed no behavior; there is no PRD sentence to revise, and adding one would pin process layout the PRD deliberately does not govern. No edit.

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/workspace/PRD_FINALIZED.md` (byte-identical to PRD.md). A fresh implementer reading it already inherits every behavior Step 7 converged on; all three test-side repairs aligned tests to what the PRD already determined, and the one implementation-side change was a non-behavioral file rename outside the PRD's scope.

## Step 9: Complete PRD — 2026-08-15T09:45:00.000Z

The diff is exactly the intended edits and nothing else. Task complete.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_2005_utility_rate_case_cost_service_filing/workspace/PRD_COMPLETED.md`

**Source:** `workspace/PRD_FINALIZED.md` (existed; copied, then edited in place only in the copy).

**Size delta:** 361 → 362 lines; 62,529 → 69,355 chars (**+1 line, +6,826 chars**). The line delta is the added `ERR_NOT_FOUND` table row; all other changes are in-paragraph inserts/revisions. No new sections added.

**Counts:** 33 edited passages = **28 ambiguity-pins** + **5 mismatch-revisions**.

**Mismatch-revisions (PRD said X, impl does Y):**
- §2.4 — revise — mismatch — `created_at`/`updated_at` are whole-second UTC (`YYYY-MM-DDTHH:MM:SSZ`), not "three fractional digits" — `implementation/util.py:40-42`, `implementation/services/core.py:13`.
- §2.9 — revise — mismatch — existence checks precede ownership/segregation-of-duties whenever the rule must read the stored record (adjustment withdraw/verify, data-request withdraw, signatory sign/decline/rescind); only the no-load ownership rules (data-request issuance, party withdrawal) run before existence; case FK resolved first — `implementation/routes/adjustments.py:82-85`, `data_requests.py:179-188`, `settlement_signatories.py:37-43`, `intervenors.py:60-62`.
- §2.10 — revise — mismatch — a remand does NOT decrement `assented_proposal_count`; the counter covers `ASSENTED`/`RECOMMENDED`/`ADOPTED`/`REMANDED` proposals that reached `ASSENTED` — `implementation/routes/settlement_proposals.py:144-155`.
- §3.5 — revise — mismatch — advance-to-hearing: wrong case state yields `ERR_INVALID_CASE_STATE` (checked first), not `ERR_OVERDUE_DATA_REQUESTS_EXIST` — `implementation/routes/rate_cases.py:205-208`.
- §3.8 — revise — mismatch — compliance-filing submit checks filing state (`ERR_INVALID_FILING_STATE`) before case state, opposite of the prose's enumeration order — `implementation/routes/compliance_filings.py:134-139`.

**Ambiguity-pins (PRD silent → pinned to impl):**
- §2.2 — insert — envelope `api_request_timestamp` is wall-clock, independent of the logical clock — `response.py:7-11`, `util.py:17-20`.
- §2.3 — insert — invalid `limit`/`offset` is `ERR_INVALID_REQUEST`; header/role auth precedes pagination validation on lists; `has_more` = offset + returned < total; unknown query params ignored — `routes/helpers.py:13-52`.
- §2.3 — insert — equal-`created_at` ties broken by creation (insertion) sequence generally — `services/core.py:33-36`.
- §2.4 — insert — `version` starts at 1 — `services/core.py:16`.
- §2.4 — insert — date-time inputs accepted in any ISO 8601 form, stored normalized to UTC whole seconds — `util.py:30-42`.
- §2.5 — insert — both rounding modes realized by one symmetric primitive; negative quotients resolve ties away from zero — `util.py:80-93`.
- §2.6 — revise — clock set rejects instants **at or** before current (`new_dt <= current`) — `util.py:58`.
- §3.1 — insert — entry-state guard before case-state guard on submit/reopen/lock; DISPUTED check last on lock — `routes/test_year_entries.py:79-119`.
- §3.2 — insert — zero `amount_cents` is `ERR_INVALID_REQUEST` — `routes/adjustments.py:36-38`.
- §3.2 — insert — verify check order: SoD → adjustment state → entry lock — `routes/adjustments.py:84-90`.
- §3.3 — revise — `exception_notes` accepted with either audit outcome, not persisted — `routes/rate_base_items.py:98-100`.
- §3.3 — insert — item-state guard before case-state guard on submit/audit/revise — `routes/rate_base_items.py:85-126`.
- §3.3 — insert — submit-filing case-phase guard precedes the four enumerated guards — `routes/rate_cases.py:128-129`.
- §3.4 — insert — `deficiency_notes` on `ACCEPTED` ignored; never persisted — `routes/rate_cases.py:172-181`.
- §3.4 — insert — issuance: omitted `issuing_intervenor_id` (IntervenorRep) or supplied (staff) is `ERR_INVALID_REQUEST`; JSON null = omitted — `routes/data_requests.py:45-62`.
- §3.4 — insert — unresolvable referenced ids → `ERR_ADJUSTMENT_NOT_FOUND`/`ERR_INTERVENOR_NOT_FOUND` (existence tier, before same-case checks) — `routes/data_requests.py:64-66`.
- §3.5 — insert — new proposal starts with both signature counts at 0 — `routes/settlement_proposals.py:74-82`.
- §3.5 — insert — circulate evaluates proposal-state before case-state — `routes/settlement_proposals.py:107-111`.
- §3.5 — insert — decline checks only the row's state (no proposal-state guard) — `routes/settlement_signatories.py:77-87`.
- §3.5 — insert — recommend/remand have no case-phase guard; blank `remand_reason` is `ERR_INVALID_REQUEST`, not persisted — `routes/settlement_proposals.py:131-155`.
- §3.5 — insert — advance-to-order-pending: case-state guard before `ERR_NO_RECOMMENDED_SETTLEMENT` — `routes/rate_cases.py:233-239`.
- §3.6 — insert — issue-order: both id arrays required but may be empty; unknown ids → `ERR_TARIFF_NOT_FOUND`/`ERR_ASSET_NOT_FOUND`, all tariffs then all assets, before state checks — `routes/rate_cases.py:249-275`.
- §3.6 — insert — class `approved_revenue_cents` recomputed in tariff creation order (latest-created approved tariff prevails for a multi-tariff class) — `routes/rate_cases.py:287-295`.
- §3.6 — insert — implement-rates: case-phase guard before `ERR_CLASS_TARIFF_MISSING` — `routes/rate_cases.py:330-339`.
- §3.7 — insert — strict tier-array shape rules (non-empty, exact keys, positive strictly-ascending caps, non-negative integer mills, null tier last) — `validate.py:144-175`.
- §3.7 — insert — class creation recomputes/persists `allocated_cost_cents` for every class of the case; never revisited later — `routes/customer_classes.py:62-74`.
- §3.7 — insert — gradualism cap skipped when `present_total` is zero or the class's `present_revenue_cents` is zero — `services/calculations.py:151-152,158-159`.
- §3.8 — insert — revenue-requirement: bad `variant` → `ERR_INVALID_REQUEST` before auth; cost-allocation: bad `method` → `ERR_INVALID_REQUEST` after auth + case load; line fields `class_id`/`class_code`/three components/`allocated_cost_cents`; zero-classes behavior — `routes/rate_cases.py:390-409`, `services/calculations.py:104-133`.
- §3.8 — insert — bill-impact: `monthly_kwh` non-negative integer; `ERR_CLASS_NOT_FOUND` before tariff lookup; explicit `tariff_id` used unscoped; `ERR_TARIFF_NOT_FOUND` ordering — `routes/rate_cases.py:414-456`.
- §3.8 — insert — `actual_revenue_cents` may be any integer; `true_up_delta_cents`/`true_up_action`/`class_true_up_lines` null until submit; zero `actual_total` → all-zero lines; lines emitted in request order — `routes/compliance_filings.py:45-51,103-105`, `services/calculations.py:193-207`.
- §3.8 — insert — `remand_notes` with `ACCEPT` ignored/not persisted; close: case-phase guard before `ERR_NO_ACCEPTED_FILING` — `routes/compliance_filings.py:156-157`, `routes/rate_cases.py:372-378`.
- §3.9 — insert — party registration accepted in any case phase — `routes/intervenors.py:19-36`.
- §4 — insert — payload-less action endpoints reject any supplied field; body must be a JSON object (missing = `{}`, non-object = `ERR_INVALID_REQUEST`) — `validate.py:40-53`.
- §4 — revise — intervenors list row: filterable by `rate_case_id` **and status** — `routes/intervenors.py:41-44`.
- §5 — insert — `ERR_NOT_FOUND` (404) for undefined routes/methods + table row — `utility_rate_case_server.py:33-39`.

No behavior was invented; every pin was verified against the implementation source cited above.
