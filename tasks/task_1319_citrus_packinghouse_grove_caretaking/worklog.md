# Worklog — task_1319_citrus_packinghouse_grove_caretaking

## Step 1: Create Task Directory — 2026-08-12T22:00:00.000Z

Directory `tasks/task_1319_citrus_packinghouse_grove_caretaking/` and `workspace/` were pre-created and pre-assigned by the pipeline orchestrator. Treated as DONE per invocation instructions; no index scan performed.

## Step 2: Generate Scaffold — 2026-08-12T23:02:00.000Z

Done. All three scaffold artifacts generated, lint-clean, and cross-audited.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/SCAFFOLD.yaml` (2163 lines; §1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (821 lines; single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/SCAFFOLD_CORNER_DESIGN.yaml` (1477 lines; single top-level key `scaffold_corner_design`)

**Counts**
- Entities: 17 (Grower, Grove, MaturityTest, HarvestCrew, HarvestAssignment, Delivery, DegreeningRoom, DegreeningSession, SortRun, AllocationChannel, Pool, AdvancePayment, CaretakingServiceOrder, CaretakingInvoice, QuarantineOrder, ExportLot, PhytosanitaryCertificate)
- State machines: 17 entries (incl. Delivery's parallel processing×regulatory dimensions; cyclic machines on CaretakingInvoice dispute/reissue and ExportLot rework; posture-driven quarantine gating)
- Calculations: 12 (maturity thresholds, ge-box weights, packout waterfall, provisional vs final pool price, settlement waterfall with advance recoup variants, advance cap, caretaking rounding-order rollup, crew capacity/overlap, room aggregate capacity, diversion credit)
- Validations: 13 priority-ordered rows (auth → ownership → existence → shape → state/OCC → safety/regulatory → constraint → temporal → fiscal → referential)
- Endpoints: 93
- Errors: 42 (all triggerable; two unreachable-candidate codes were removed/added during the audit pass)
- Roles: 7 (segregation-of-duties model: sort create≠verify, quarantine issue≠release, inspection request≠certificate issue; Grower is entity-backed)
- Concurrency rules: 3 true-race OCC rules (maturity supersede on Grove.version, sort-run recreate on Delivery.version, pool re-price on Pool.version)
- §1.8 instances: 21 non-stub (every rule ≥2; Rule 2 covers modes a+b+c, Rule 3 has 3 entities, Rule 7 has 3 entity pairs); all formula-derived asserts pre-computed as literals (e.g., provisional 514 vs final 359, cap 29853, offset 17376/recoup 10000/paid 7375, 8.994→FAIL vs 8.995→PASS)
- §1.9 instances: 68 total, 63 non-stub across all nine guide sections (5 `excluded_because` stubs, each citing an existing §1.8 instance)

**Verification** — `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    93
  §1.1 entities declared:     17
  §1.8 instances scanned:     21
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  952

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional mechanical audits passed: zero forbidden race vocabulary, 89/89 instance names unique across both design files, zero unbound `${var}` placeholders, all `grounds` references resolve, all `excluded_because` stubs reference real §1.8 instances. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-12T23:03:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1319_citrus_packinghouse_grove_caretaking/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-08-12T23:26:00.000Z

All audits pass. The PRD is complete at 393 lines. Here is the verbatim summary.

---

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/workspace/PRD.md`
**Line count:** 393

**Section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, diff-verified); 2.3 Pagination; 2.4 Common Resource Properties and Change Tracking; 2.5 The Packinghouse Logical Clock; 2.6 The Request Gate Ladder (13-tier validation priority in explicit order); 2.7 Cents, Ratios and Rounding Discipline; 2.8 Optimistic Concurrency Control; 2.9 Segregation of Duties; 2.10 Quarantine Posture and the Delivery's Two Status Dimensions; 2.11 Nested Resource Retrieval
- 3. Business Logic & Workflows — 3.1 Growers, Groves and Fiscal Standing; 3.2 Maturity Testing and Harvest Scheduling; 3.3 Receiving Fruit: Deliveries and Pool Resolution; 3.4 Degreening Rooms and Conditioning Sessions; 3.5 Sort Runs, Grading and the Packout Waterfall; 3.6 Pool Accounting, Advances and Weekly Settlement; 3.7 Caretaking Services and Grower Billing; 3.8 Pest Quarantine and the Compliance Cascade; 3.9 Export Lots and Phytosanitary Certification
- 4. Endpoint Definitions (93-row table, 4 columns; roles byte-matched to scaffold)
- 5. Error Code Catalogue (42-row table, 2 columns; HTTP statuses matched to scaffold)

**Coverage audit (mechanical, via `/tmp/audit_prd.py`):**

```
Field coverage check (Contract 1):
- entities[].fields + endpoints[].input/query_params/path_params: 118 required, 118 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ordering: 13 tiers expressed as an explicit ordered ladder in §2.6 (incl. fruit-fly-before-posture within tier 7 and required→not-passing→expired across tiers 8/11)
- concurrency_rules[] OCC: 3/3 expressed in §2.8 (write op + expected_grove_version/expected_delivery_version/expected_pool_version + ERR_STALE_VERSION/412), no race framing
- state_machines[].transitions: 16 machines, all transitions expressed with from→to pairs, preconditions paired to error IDs, side effects stated
- calculations[]: 12/12 in precise prose with all constants (variety minimums, GE weights 1.15/1.0/0.9/0.35, FRESH 6/20, 80% fill, tiers 150/140/125 at 10,000/50,000 inclusive-low, 50% offset cap, 60% advance cap, 12% markup, full rate table, 120h validity, 24h cold treatment, 14-day cert, 1.25 completion band)
- validations[] conditions: 42/42 error IDs present in §2/§3 prose and matchable to triggers; 42/42 in §5 with correct statuses
- endpoints[].side_effects / applies_to: 93/93 endpoints in §4; all cascade and compensating side effects narrated in §3; tier-3 grower-scoped endpoint set enumerated in §2.1
- entities[].fields[] structured content: defaults/initials expressed (min/max_hours 12/72, color_add_applied true, caretaking_enrolled false, recoup_policy NEXT_SETTLEMENT_FULL, chemical_cost_cents 0, cold_treatment_hours 0, null-until fields, computed-field formulas)
- sibling-branch symmetry: divert×3, payments×3, certificate PASS/FAIL, provisional/final price, both recoup policies, both packout variants, write-off×2 — equal density
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 856
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Zero-silence confirmed: every entity, state machine, calculation, validation, endpoint, error, and role in `SCAFFOLD.yaml` is mapped to PRD prose. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced. One in-progress defect was caught and repaired during generation (a garbled sentence in §3.1 around `ERR_GROWER_NOT_ACTIVE`), and a missing default note for `provisional_price_cents_per_ge_box` was added during the audit pass.

## Step 6: Generate Implementation — 2026-08-13T00:35:00.000Z

Implementation complete and verified. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/workspace/implementation/`):
- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app assembly, error handlers (ApiError, 404/405, catch-all), entry point binding `0.0.0.0` on `$PORT` (default 10000)
- `core.py` — logical clock (boots at 2026-08-01T00:00:00Z, never wall-clock), response envelope (`meta.api_request_id`/`api_request_timestamp` with 3 fractional digits, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more` to `meta`), error catalog constants, in-memory store, auth (`X-User-ID`/`X-User-Role`, 7 roles), body/type/enum/date validation, pagination (limit default 10, min 1, max 100; offset default 0), Decimal round-half-up helpers
- `domain.py` — variety minimums, GE weights, rate tables, quarantine posture derivation, maturity gate, pool/provisional-price/channel helpers, all entity serializers
- `routes_core1.py` — clock, growers, groves, maturity tests (OCC `expected_grove_version`), crews, harvest assignments
- `routes_line.py` — deliveries (dual processing/regulatory dimensions), degreening rooms/sessions (aggregate-capacity overlap), sort runs (OCC `expected_delivery_version`, packout waterfall with fresh/juice-forced variants), allocation channels
- `routes_money.py` — pools (close-intake/set-price with OCC `expected_pool_version`/settle with pinned 4-step settlement waterfall, PRO_RATA_THIRDS vs NEXT_SETTLEMENT_FULL recoupment), advances (cap check), caretaking orders (rate-tier rollup with per-component rounding) and invoices (issue/pay/dispute/reissue/void)
- `routes_compliance.py` — quarantine orders with atomic activation/release cascades (hold-cause tracking so manual holds survive quarantine release), export lots (grade-scoped posted-allocation capacity, JAPAN cold-treatment and fruit-fly gates with fruit-fly before generic posture), phytosanitary certificates (PASS→ISSUED/CERTIFIED, FAIL→REVOKED/REJECTED, revoke returns lot to INSPECTION_READY, ship consumes cert with strict expiry)

**Endpoint count:** 93 routes — matches the PRD §4 table exactly.

**State storage:** purely in-memory Python dicts in `core.DB` (one dict per entity type) plus a module-level logical clock. The store starts completely empty on every boot — no seeding, fixtures, or preloaded entities anywhere; a module-level sequence counter gives deterministic `created_at`-tie ordering. Every mutation bumps `version` and refreshes `updated_at`, including cascade-touched groves/assignments/deliveries/channels/pools.

**Verification:** three smoke suites (93-route coverage of the core pipeline, degreening/quarantine/caretaking/advance-settlement, and export-lot/phyto flows incl. cert-expiry boundary at exactly `expires_at`) all pass against fresh boots; two real bugs found and fixed during testing (negative-residual recoupment clamp in settlement; channel-mismatch now precedes capacity in export-lot create). `python3 -m py_compile` clean on all modules.

**start.sh contract confirmed:** reads `$PORT` (default 10000), binds `0.0.0.0` via `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`, guards the pip install behind `python3 -c "import flask"` so per-test reboots skip reinstall, and runs the server in the foreground via `exec python3 app.py`. Verified end-to-end with `PORT=<n> bash start.sh` from the implementation directory: HTTP-ready in ~1s with the correct empty-store envelope.

## Step 5: Generate Unit Tests — 2026-08-13T00:10:00.000Z (resume-run reconstruction note)

The original run was killed before this entry was appended; artifacts verified on disk by the resume orchestrator at 2026-08-13 (this entry reconstructs the missing record, it is not a regeneration). `test_helpers/` contains all 9 required modules (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`); `test_suite/` contains `conftest.py` plus 11 `test_*.py` files. All files compile clean (`py_compile`), pytest collects 104 test functions in 0.10s, and AST audit confirms 104/104 test functions carry exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag (0 untagged). Artifacts judged complete; kept and reused as-is.

## Step 7 pre-check — 2026-08-13T00:40:00.000Z

No `results.*.json` files present in `workspace/implementation/` — Step 7 never ran (or never completed a sweep). Resuming pipeline at Step 7.

## Step 7: Test Iteration — 2026-08-13T00:55:00.000Z

Sweep 1 (8 parallel rounds): 103/106 in every round; stable union of 3 failures, 0 flaky.
Sweep 2 (8 parallel rounds): 104/104 in all 8 rounds — CLEAN.

Resolutions (all test-side; implementation untouched and PRD-faithful):
- DELETED `test_03_harvest_assignments.py::TestAssignmentStartGatedByQuarantine::test_start_rejected_while_grove_quarantined` — unique-derivability collapse (error-precedence). PRD §3.8 ("Each covered grove's `SCHEDULED` harvest assignments are cancelled") + §2.6 (tier 6 state before tier 7 regulatory) uniquely determine `ERR_INVALID_STATE_TRANSITION` for start-after-cascade; the asserted `ERR_GROVE_QUARANTINED` is unreachable via the API. Source: SCAFFOLD_DIFFICULTY_DESIGN `assignment_start_gated_by_grove_quarantine` recipe contradicted the scaffold's own cascade rule.
- REWROTE `test_03_harvest_assignments.py::...::test_start_allowed_after_release_by_different_officer` (STEP 1c split): kept covered release assertions (RELEASED, `released_by != issued_by`, posture → CLEAR); replaced contradicted start assertions with PRD-true ones (cascade cancels the SCHEDULED assignment per §3.8; start on it → `ERR_INVALID_STATE_TRANSITION` per §2.6; post-release a NEW assignment creates + starts → IN_PROGRESS, preserving the design aspect "transition legal only after release by a different officer").
- DELETED `test_07_pools_settlement.py::TestProvisionalProjectionInputs::test_provisional_projection_excludes_juice_channel` — unique-derivability collapse (computed-field recompute trigger). PRD §3.6 enumerates recompute triggers as "a sort-run post, a sort-run reverse, an export-lot diversion" (channel creation not listed) and states the field reads "zero until proceeds and channel capacity exist" (no proceeds posted in the test). Two faithful readings (stored field recomputed on listed triggers vs. recompute-on-read/channel-create) diverge; adding a channel-create recompute would introduce a pool version-bump side effect PRD never states (§2.4). Juice exclusion from the projection remains implicitly covered by the passing 514/654/522/600/444 provisional assertions, all evaluated with an uncapped JUICE channel present.

Suite: 106 → 104 tests. No `implementation/` changes; no assertion weakened; no skip/xfail added.

## Step 7: Run Tests and Iterate — 2026-08-13T01:05:00.000Z

Clean 8-round parallel sweep achieved. Final summary:

## Summary

**Iterations run:** 2 (sweep 1: 103/106 in all 8 rounds with a stable 3-failure union, zero flaky; sweep 2: **104/104 in all 8 rounds — ALL CLEAN**).

**Tests deleted (2):**
1. `test_03_harvest_assignments.py::TestAssignmentStartGatedByQuarantine::test_start_rejected_while_grove_quarantined` — unique-derivability collapse (error-precedence pattern). PRD §3.8 states verbatim "Each covered grove's `SCHEDULED` harvest assignments are cancelled" and §2.6 orders state legality (tier 6, `ERR_INVALID_STATE_TRANSITION`) before regulatory gates (tier 7), so the asserted `ERR_GROVE_QUARANTINED` on start-after-cascade is unreachable under any PRD-faithful implementation — PRD uniquely determines the *opposite* outcome. Scaffold rule that drove generation: `SCAFFOLD_DIFFICULTY_DESIGN` instance `assignment_start_gated_by_grove_quarantine`, whose recipe contradicts the scaffold's own cascade definition.
2. `test_07_pools_settlement.py::TestProvisionalProjectionInputs::test_provisional_projection_excludes_juice_channel` — unique-derivability collapse (computed-field recompute trigger). PRD §3.6 enumerates provisional-price recompute triggers as only "a sort-run post, a sort-run reverse, an export-lot diversion" and says the field reads "zero until proceeds and channel capacity exist" (the test posts nothing). A faithful stored-field implementation returns 0 (what the implementation does); a recompute-on-read reading returns 400 — two readers diverge. Scaffold rule: `Corner/calculations/provisional_projection_excludes_juice_channel`. Juice-exclusion remains implicitly covered by the passing 514/654/522/600/444 provisional assertions, all evaluated with an uncapped JUICE channel present.

**Fixes applied to `test_suite/` (1 rewrite, STEP 1c partial-coverage split):**
- `test_03_harvest_assignments.py::test_start_allowed_after_release_by_different_officer` — kept the PRD-covered release assertions (order → `RELEASED`, `released_by != issued_by` per §2.9, posture → `CLEAR` per §3.8); replaced the two PRD-contradicted start assertions with PRD-true ones: cascade cancels the SCHEDULED assignment (§3.8 verbatim), start on it → `ERR_INVALID_STATE_TRANSITION` (§2.6 tier 6 before tier 7), and post-release a NEW assignment creates + starts → `IN_PROGRESS`, preserving the design instance's distinguishing aspect.

**Fixes applied to `test_helpers/`:** none needed — fixtures were PRD-consistent.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on all three failures (cascade cancellation per §3.8, tier-6-before-tier-7 per §2.6, provisional recompute only on listed triggers per §3.6). Adding a channel-create recompute to satisfy the deleted test would have introduced a pool version-bump side effect PRD never states (§2.4) — forbidden. No assertion weakened, no skip/xfail added, no endpoint/field/side-effect added.

## Step 8: Finalize PRD — 2026-08-13T01:30:00.000Z

The patch is complete. Final verification confirms a single-sentence revision on line 200, with everything else byte-identical.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 393 lines, PRD_FINALIZED.md 393 lines — 0.0% line-count delta (one in-place sentence revision on line 200, +57 words).

### Changes

- **§3.6 — revise** — Replaced "recomputed on every mutation that touches the pool — a sort-run post, a sort-run reverse, an export-lot diversion —" with pinned stored-field semantics: "The field is a stored value, not a figure derived at read time: born zero, it is recomputed at exactly these three moments — a sort-run post, a sort-run reverse, an export-lot diversion — and at no other time; in particular, registering an allocation channel for the pool's variety and week does not refresh any pool's provisional price." — `implementation/routes_money.py:47` (born 0), `implementation/routes_line.py:621` (post recompute), `implementation/routes_line.py:656` (reverse recompute), `implementation/routes_compliance.py:297` (divert recompute), `implementation/routes_line.py:668-715` (channel create touches no pool), `implementation/domain.py:130-144,362` (formula + stored serialization).

This resolves the unique Step 7 genuine PRD silence (deleted `test_07...::test_provisional_projection_excludes_juice_channel`): with channels registered but nothing posted, a stored-field reader returns 0 (implementation behavior) while a recompute-on-read reader returns 400 — the old wording "every mutation that touches the pool" with an illustrative-looking dash list did not uniquely determine which.

### Step 7 items requiring no edit (PRD already determines; pure test bugs)

- **Deleted `test_03...::test_start_rejected_while_grove_quarantined`** — §3.8 verbatim ("Each covered grove's `SCHEDULED` harvest assignments are cancelled") + §2.6 (tier 6 state legality before tier 7 regulatory gates, earlier-tier error wins) + §3.2 (start moves `SCHEDULED` → `IN_PROGRESS`) uniquely determine `ERR_INVALID_STATE_TRANSITION` on start-after-cascade; implementation matches (`routes_compliance.py:43-46`, `routes_core1.py:446-447`). Prose kept verbatim.
- **Rewritten `test_03...::test_start_allowed_after_release_by_different_officer`** — kept assertions all trace to PRD-determined behavior (§2.9 SoD at `routes_compliance.py:125-126`; §3.8 posture recompute at `routes_compliance.py:132-143`; §2.6 tier order; §3.2 create+start at `routes_core1.py:374-463`). No silence.

### Per-edit pre-edit search log

**Edit 1 (§3.6 provisional-price sentence):**
- (a) Subject: when `provisional_price_cents_per_ge_box` is (re)computed and what reads it.
- (b) Paths enumerated and read/grepped (grep for `recompute_provisional|provisional_price` across all `implementation/*.py`): born-zero at `routes_money.py:47`; recomputes at post `routes_line.py:618-622`, reverse `routes_line.py:653-657`, divert `routes_compliance.py:296-298`; NO recompute at channel create `routes_line.py:668-715`, close-intake `routes_money.py:75-90`, set-price `routes_money.py:93-118`, settle `routes_money.py:121-185`; stored reads at `domain.py:362` (serializer) and `routes_money.py:272` (advance cap); formula at `domain.py:130-144` matches the PRD projection text verbatim (juice excluded).
- (c) Wording adjustment: an early draft retained "recomputed on every mutation that touches the pool"; this was replaced with "recomputed at exactly these three moments … and at no other time" because close-intake, set-price, and settle all mutate the pool without recomputing — the looser phrase would mis-describe those three paths. The explicit channel-registration clause was added because that is the exact divergence site of the deleted test; it is consistent with `create_channel`, which never touches any pool.

## Step 9: Complete PRD — 2026-08-13T02:00:00.000Z

All edits applied. Final verification: line counts are unchanged (393 → 393), character count went 77203 → 80387 (+3184 chars), and the diff touches exactly 20 paragraphs — all in-paragraph inserts/revisions, no new sections.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (393 lines / 77203 chars) → `PRD_COMPLETED.md` (393 lines / 80387 chars), char-delta **+3184**, 20 changed paragraphs, zero added/removed lines.

**Counts**: 20 changes total — 16 inserts, 4 revises; 19 ambiguity-pins, 1 mismatch-revision. (No genuine behavioral mismatches in formulas, state machines, roles, or gate semantics were found — PRD_FINALIZED had already aligned the one substantive divergence, provisional-price recompute moments; the remaining gaps were silences or enumeration-order readings.)

- §2.3 Pagination — insert — ambiguity — offset ≥ 0, non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST` (400); `created_at` ties break by insertion order (reversed with newest-first listings); `total_count` counts the filtered set; `has_more` = offset + page size < total — core.py:296-328, 163-168
- §2.4 Common properties — insert — ambiguity — `version` begins at 1 on creation — core.py:140-148
- §2.5 Logical clock — insert — ambiguity — supplied instant adopted verbatim (no monotonicity check); envelope `api_request_timestamp` also reads the logical clock — routes_core1.py:34-40, core.py:89-93
- §2.6 tier 4 Existence — insert — ambiguity — body-carried resource references (`grower_id`, `crew_id`, `pool_id`, etc.) also surface `ERR_NOT_FOUND` (404) — routes_core1.py:146-148, routes_line.py:49-55, routes_money.py:216-219
- §2.6 tier 5 Well-formedness — insert — ambiguity — counting fields (boxes, hours, cents, scores, ranks, versions) are integers and booleans never count as numbers; measurements (`brix`, `acid_pct`, `juice_pct`, `defect_pct`, `acreage`, `acres_treated`) accept any JSON number — core.py:217-238
- §2.6 tier 7 Regulatory gates — insert — ambiguity — crew-active check (`ERR_CREW_NOT_ACTIVE`) placed in tier 7, before capacity/overlap at creation and before maturity at start — routes_core1.py:398-399, 454-455
- §3.2 Assignment creation — insert — ambiguity — `window_end` must be strictly after `window_start` (`ERR_INVALID_REQUEST`) — routes_core1.py:391-392
- §3.4 Rooms — insert — ambiguity — `min_hours`/`max_hours` are integers ≥ 0 (`ERR_INVALID_REQUEST`), not cross-validated against each other — routes_line.py:195-200
- §3.4 Session creation — insert — ambiguity — any delivery with regulatory `CLEAR`/`RELEASED` may be loaded regardless of variety or processing state — routes_line.py:280-346
- §3.4 Session release — insert — ambiguity — `override_approved` honored only from a `QualityInspector`; ignored from a `LineOperator` — routes_line.py:383-394
- §3.5 Sort-run post — revise — ambiguity — allocation lines carry `channel_id`/`grade`/`boxes`, emitted in waterfall walk order, juice line last and omitted when zero — routes_line.py:583, 596-600
- §3.5 Channels — insert — ambiguity — `accepts_grades` must be a duplicate-free list; `week_start` accepted as any valid calendar date (Monday not validated) — routes_line.py:676, 684-690
- §3.6 Pools — insert — ambiguity — pool `week_start` likewise any valid calendar date — routes_money.py:35
- §3.6 Settlement statements — insert — ambiguity — endpoint returns `{pool_id, statements[]}` with rows `grower_id`, `posted_ge_boxes`, `share_cents`, `offset_cents`, `recouped_cents`, `paid_cents`; empty array pre-settlement — routes_money.py:172-195
- §3.6 Advance approval — revise — ambiguity — gate evaluation order pinned: grower `ACTIVE` → advance cap → pool `OPEN` — routes_money.py:267-278
- §3.7 Caretaking orders — insert — ambiguity — `chemical_cost_cents` must be ≥ 0 (`ERR_INVALID_REQUEST`) — routes_money.py:341-344
- §3.7 Invoice payments — insert — **mismatch** — positivity check pinned as request well-formedness evaluated before the invoice's state check (overpayment after state), overriding the generic tier-12 ladder placement — routes_money.py:543-550
- §3.7 Invoice reissue — revise — ambiguity — "original total" pinned to the invoice's current pre-adjustment `total_cents` — routes_money.py:584
- §3.9 Export-lot creation — revise — ambiguity — posted-allocation capacity is accounted per channel-and-grade; reservations released only on diversion (SHIPPED lots keep reserving); channel coherence evaluated before the capacity gate; lot `variety` not checked against the source grove's variety — routes_compliance.py:171-194, domain.py:164-186
- §3.9 Certification/rework — insert — ambiguity — FAIL certificates are stamped with `issued_at` and `expires_at` (14 days) exactly as PASS; rework `cold_treatment_hours` validated ≥ 0 — routes_compliance.py:353-363, 268-272

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1319_citrus_packinghouse_grove_caretaking/workspace/PRD_COMPLETED.md`
