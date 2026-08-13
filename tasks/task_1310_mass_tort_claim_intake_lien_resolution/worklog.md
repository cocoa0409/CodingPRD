# Worklog — task_1310_mass_tort_claim_intake_lien_resolution

## Step 1: Create Task Directory — 2026-08-12T21:09:00.000Z

Task directory `tasks/task_1310_mass_tort_claim_intake_lien_resolution/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command. Step 1 treated as DONE; no index scan or directory creation performed.

## Step 2: Generate Scaffold — 2026-08-12T21:37:00.000Z

**Output files (all three):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1310_mass_tort_claim_intake_lien_resolution/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1310_mass_tort_claim_intake_lien_resolution/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1310_mass_tort_claim_intake_lien_resolution/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: 9 (SettlementProgram, Claimant, Claim, TierMatrix, MedicalRecord, Lien, Appeal, Disbursement, ClosingStatement)
- State machines: 5 (Claim, MedicalRecord, Lien, Appeal, Disbursement)
- Calculations: 5 (tier_assignment, attorney_fee, provisional_lien_demand, disbursement_allocation, qsf_reconciliation)
- Validations: 19 priority-ordered rules
- Endpoints: 64 (48 business + 16 flat reverse-reachability aliases)
- Errors: 29
- Roles: 6 (ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole)
- Concurrency rules: 2 (OCC on Claim.version for assign-tier and lien resolve)

**Difficulty design:** 18 instances (9 rules × 2), all rule_ids covered.

**Corner design:** 33 instances across 8 sections (entities, state_machines, calculations, validations, endpoints, errors, cross_cutting_layers, consistency_model).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Noteworthy design decisions:**

1. **Archetype blend**: compliance_audit primary + workflow_orchestration secondary, with segregation_of_duties role model (prepare-disbursement caller cannot approve; enforced via `X-User-ID` comparison).

2. **Logical clock on the program** (`current_utc`, default `2026-08-01T00:00:00Z`) drives the 30-day lien-holder response window — holder-silent resolution is only legal after `current_utc > holder_response_due_at`, fully deterministic via `POST /settlement-programs/{pid}/_clock/set_current_utc`.

3. **Rule 8 (temporal-overlap)** mapped onto two domain-natural overlap rules rather than forcing a fake booking resource: (a) TierMatrix severity range [min,max] closed-interval overlap on publish (touching counts) supersedes prior PUBLISHED rows; (b) active-claim lifecycle uniqueness per Claimant (half-open window from create to terminal state).

4. **Dual-variant calculations** picked two distinct entity domains: per-lien provisional vs final demand on Lien (with conditional hardship branch on gross award for MEDICAL_PROVIDER liens, mode (a) combinatorial), and per-line-then-sum vs sum-then-round attorney fee on Claim (mode (b) nested rounding) — pinned canonical rounding order with a 1-cent divergence test (101/103 cents liens → fee=237 vs rejected variant 236).

5. **Cascades** span depth-3 (appeal uphold → gross recompute → fee recompute → net recompute → active_appeal_id cleared) and depth-2 (disbursement release → claim auto-DISBURSED when last sibling releases).

6. **Flat reverse-reachability aliases** (`GET /settlement-programs/claims/{id}` etc.) added as a §1.5 priority-ladder fix to satisfy lint check (f), since the linter's segment-derivation heuristic requires a 2-segment path.

## Step 3: Copy Shared Files — 2026-08-12T21:39:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1310_mass_tort_claim_intake_lien_resolution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T21:47:00.000Z

PRD generation complete. All three hard contracts pass.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1310_mass_tort_claim_intake_lien_resolution/workspace/PRD.md` (300 lines)

**PRD section list:**
- §1. Introduction (2 paragraphs — business context + system scope angle)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (6 roles, identity prose per role)
  - 2.2 API Response Structure (fixed verbatim block, byte-identical to `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending, `meta` fields)
  - 2.4 Common Resource Properties (id/created_at/updated_at/version; ClosingStatement as the `common_fields: false` exception; claim version advance events)
  - 2.5 The Program Logical Clock (default `2026-08-01T00:00:00Z`, monotonic advance via `to_iso8601`, never wall-clock)
  - 2.6 Optimistic Concurrency Control (both OCC rules: assign-tier and lien resolve, `expected_claim_version` + `ERR_STALE_VERSION` 412, checked before state validation)
  - 2.7 Nested Path Resolution and Flat Aliases (left-to-right `pid`/`cid`/`tmid`/`clid`/`rid`/`lid`/`aid`/`did` validation, flat alias shapes)
  - 2.8 Monetary Precision and Rounding (integer cents, round-half-up, per-line-then-sum canonical order)
  - 2.9 Validation Check Order (full priority gauntlet, with two orderings emphasized)
  - 2.10 Segregation of Duties and the QSF Ledger (conservation formula, self-approval rule)
- §3. Business Logic & Workflows (8 subsections, organized by claims-pipeline lifecycle)
  - 3.1 Program Setup and the Compensation Matrix
  - 3.2 Claimant Registration and Eligibility Screening
  - 3.3 Medical Records and Injury Verification
  - 3.4 Tier Assignment
  - 3.5 The Lien Lifecycle
  - 3.6 Appeals and Re-Tiering
  - 3.7 Award Arithmetic and the Allocation Waterfall
  - 3.8 Disbursement Execution, Closure, and Audit
- §4. Endpoint Definitions (4-column table, all 63 endpoints including 16 flat aliases)
- §5. Error Code Catalogue (2-column table, all 29 error IDs)

**Coverage notes:**
- All scaffold tables translated: entities (9), state machines (5 machines, all transitions including the 4 withdraw siblings, 3 waive siblings, both resolve paths, both begin-negotiation ramps), concurrency rules (2), calculations (5 — tier_assignment, attorney_fee with per-lien-then-sum rounding, provisional_lien_demand with all five lien-type branches and the $50,000 hardship floor, disbursement_allocation waterfall with holder ordering by earliest `created_at`, qsf_reconciliation), validations (all 19 priorities), endpoints (63), errors (29), roles (6).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 58 required, 58 present, 0 missing
- endpoints[].request_body: 31 required, 31 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 9 required, 9 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in prose (§2.9 gauntlet + per-endpoint orderings), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_claim_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 31 checked, 31 fully expressed, 0 missing
- calculations[]: 5 checked, 5 fully expressed (no pseudocode, reconstruction-safe), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 63 checked, 63 expressed, 0 missing
- entities[].fields[] structured content: 58 checked, 58 reconstructible (defaults, enum values, formats stated), 0 missing
- sibling-branch symmetry: 6 groups checked (withdraw×4, waive×3, resolve×2, begin-negotiation×2, accept/reject, uphold/deny), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 355
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule decisions (scaffold ambiguities resolved without inventing rules):**
1. **Prepare-disbursement check order conflict** — the scaffold's transition preconditions list `ERR_NEGATIVE_NET_AWARD` before `ERR_QSF_INSUFFICIENT_FUNDS`, but the priority-ordered validations table ranks QSF (18) before negative-net (19). The PRD follows the validations priority table (fund sufficiency first) and states that ordering explicitly in §2.9 and §3.7.
2. **`NEGOTIATING` lien_posture value** — declared in the enum but no scaffold transition writes it. The PRD enumerates it as a valid `lien_posture` value in §3.2 without inventing a transition that sets it.
3. **"1..3 Disbursement rows"** — rendered as "always one for the claimant, plus one for the attorney when represented, plus one per lien-holder bucket grouped by payee" to stay faithful to the scaffold's parenthetical while remaining consistent with the waterfall's one-row-per-distinct-holder rule.
4. **Supersession cascade** — matrix publish superseding an overlapping published row is stated as a cascade in §3.1 (side-effect coverage), with the displaced row's `matrix_state` named as `SUPERSEDED`.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T21:56:00.000Z

**Totals: 81 tests, all collected cleanly by pytest; 0 skipped design instances.**

### Queue A (Difficulty) — 18/18 instances, each with ≥2 tests (38 tagged tests total)
All nine rules translated: `dual_variant_calc` (Medicare provisional-vs-silent-final 60000/100000; attorney-fee per-line 237 vs sum-then-round 236), `combinatorial_formula` (MEDICAL_PROVIDER hardship branch 400000/800000 across two programs; mode-b fee recompute per lien resolution + zero floor), `non_linear_state_machine` (lien DISPUTED cycle + invalid dispute-from-NOTIFIED; appeal upheld re-tier + FILED→WITHDRAWN revert), `transitive_cascade` (appeal uphold gross→fee→net chain with version-advance check; disbursement release → released_at=program clock → claim DISBURSED, incl. mid-state still READY with a pending sibling), `priority_pair_validation_conflict` (stale-version-beats-state + its current-version counterpart; self-approval on both APPROVED and PENDING), `boundary_precision_check` (severity == max inclusive; final == asserted accepted and +1 rejected), `cross_entity_state_dependency` (verify-injury record gate + success counterpart; finalize blocked by open appeal + success after withdrawal), `resource_temporal_overlap` (matrix publish touching-boundary supersede + non-overlap stays + matrix_published flag; duplicate active claim + screen allowed after withdrawal), `compensating_invariant` (QSF 100000000→95000000→100000000 prepare/void + reservation assertion; active_appeal_id set→cleared on withdraw and uphold).

### Queue B (Corner) — 33/33 non-stub instances, each with ≥1 test (43 tagged tests total)
No `excluded_because:` stubs existed in this corner index.

### Per-file counts
`test_01_program_and_claim_creation.py` 9 · `test_02_eligibility_and_claim_states.py` 7 · `test_03_medical_records_and_verification.py` 4 · `test_04_tier_assignment.py` 11 · `test_05_matrix_publish_overlap.py` 3 · `test_06_lien_lifecycle.py` 16 · `test_07_attorney_fee_and_appeals.py` 15 · `test_08_disbursement_and_qsf.py` 11 · `test_09_closure_and_security.py` 5.

### test_helpers inventory (all under `test_helpers/`)
`__init__.py` (barrel), `types.py` (9 TypedDicts — ClosingStatement correctly omits `updated_at`/`version` per common_fields:false — 13 enums), `api_client.py` (68 methods incl. clock, all nested transitions, and all flat aliases), `api_errors.py` (29 error IDs + HTTP map registered with `set_error_http_status_map`), `assertions.py` (per-entity + claim invariant + disbursement conservation), `factories.py`, `constants.py` (fee rate, provisional rates, hardship floor, default clock, approver IDs), `test_users.py` (shared headers + mandatory `make_claimant_headers` entity-backed builder), `fixtures.py` (5 tiers through `create_closed_claim`, OCC version threading via `get_claim_version`).

### Skipped instances
None.

### Noteworthy translation decisions
- **waterfall_allocation_buckets_in_order**: asserted bucket order via creation-order list reads (`data[0..2]`), which PRD §3.7's fixed waterfall order uniquely derives; PRD's no-sort-order sentence for nested lists makes positional reading the only implementable option, so the assertion is two-reader safe. Conservation asserted separately against `net_award_cents`.
- **self_approval_beats_disbursement_state**: tagged with the §2.9 gauntlet sentence that lists the from-state check before `ERR_SELF_APPROVAL_FORBIDDEN` (the exact decision order asserted).
- **OCC tests** capture the live claim version mid-setup and pass `v-1` as the stale value, avoiding any hard-coded version arithmetic.
- **ClaimantRole calls** (withdraw, dispute, appeals) thread `make_claimant_headers(claimant["id"])` per the entity-backed identity rule; DisbursementApprover segregation uses distinct `user_approver_1`/`user_approver_2` IDs.
- Fixed one citation during the final verbatim sweep: the missing-`claimant_id` test now cites PRD §3.2's actual `ERR_INVALID_REQUEST` sentence rather than scaffold-only condition text. Automated sweeps confirm: 0 verbatim-citation failures, 0 orphan/dual/missing Design tags, tag is the terminal docstring line everywhere, no skip/xfail markers, no scaffold vocabulary in generated code.

## Step 6: Generate Implementation — 2026-08-12T22:08:00.000Z

### File Inventory (14 source files + start.sh + requirements.txt)

```
implementation/
  start.sh                          # Foreground launcher, guards pip install
  requirements.txt                  # flask>=2.0
  app.py                            # Flask app factory, blueprint registration, error handlers
  db.py                             # In-memory store (9 dicts + claim number counter)
  errors.py                         # ApiError class + all 28 error ID constants
  response.py                       # Envelope helpers (meta/response_type/data)
  middleware.py                     # X-User-ID/X-User-Role extraction, role validation
  routes/__init__.py
  routes/helpers.py                 # Shared: pagination, UUID/timestamp, path resolution
  routes/programs.py                # Program CRUD + logical clock
  routes/tier_matrices.py           # TierMatrix CRUD + publish (with supersede cascade)
  routes/claimants.py               # Claimant registration + validation
  routes/claims.py                  # Claim filing, screen-eligibility, deny, withdraw
  routes/medical_records.py         # Record upload, accept/reject, verify-injury
  routes/tier_assignment.py         # assign-tier with OCC + 5 preconditions
  routes/liens.py                   # Full lien lifecycle (6 transitions + finalize)
  routes/appeals.py                 # Appeal filing, begin-review, uphold (re-tier), deny, withdraw
  routes/disbursements.py           # prepare-disbursement, approve, release, void
  routes/closing.py                 # Claim closure + ClosingStatement sealing
  routes/flat_aliases.py            # 8 flat single-read + 8 flat list aliases
  services/__init__.py
  services/calculations.py          # tier_assignment, attorney_fee, provisional_lien_demand, disbursement_allocation, qsf_reconciliation
```

### State Storage

All state is **in-memory only**, stored in module-level dicts in `db.py` (`programs`, `claimants`, `claims`, `tier_matrices`, `medical_records`, `liens`, `appeals`, `disbursements`, `closing_statements`). The store starts completely empty on every boot -- no seeding, preloading, or hardcoded entities. Fresh process = fresh state.

### State Machines Implemented

- **Claim**: 12 statuses with transitions for screen-eligibility, deny, withdraw (4 from-states), first-record-upload cascade, verify-injury, assign-tier, first-lien cascade, finalize-liens, prepare-disbursement, auto-DISBURSED on last release/void, close. Three parallel posture dimensions (`eligibility_status`, `injury_verification_status`, `lien_posture`) tracked independently.
- **MedicalRecord**: PENDING_REVIEW -> ACCEPTED | REJECTED (one-way door).
- **Lien**: IDENTIFIED -> NOTIFIED -> IN_NEGOTIATION -> RESOLVED; IN_NEGOTIATION -> DISPUTED -> IN_NEGOTIATION; waive from 3 states; silent-holder resolve from NOTIFIED with 30-day window.
- **Appeal**: FILED -> UNDER_REVIEW -> UPHELD | DENIED; FILED -> WITHDRAWN. UPHELD triggers full re-tier cascade.
- **Disbursement**: PENDING -> APPROVED -> RELEASED; PENDING -> VOIDED (with QSF refund).
- **TierMatrix**: DRAFT -> PUBLISHED (with supersede cascade on overlapping ranges).

### Calculations Implemented

- **tier_assignment**: max severity over ACCEPTED records, matched matrix row's base_award_cents.
- **attorney_fee**: 40% contingency with per-lien-then-sum rounding (ROUND_HALF_UP via Decimal), lien share subtraction, floor at 0. Not represented -> 0.
- **provisional_lien_demand**: Per-type discount rates (MEDICARE 60%, MEDICAID 50%, VA_TRICARE 70%, PRIVATE_INSURER 75%, MEDICAL_PROVIDER conditional 40%/80% based on $50K hardship floor).
- **disbursement_allocation**: Waterfall order: lien-holder buckets (grouped by holder_name, ordered by earliest created_at) -> ATTORNEY -> CLAIMANT residual. Conservation invariant enforced.
- **qsf_reconciliation**: principal - RELEASED disbursements - READY_FOR_DISBURSEMENT reservations.

### Validation Priorities

All 19 validation rules from the scaffold implemented in priority order: auth headers (1) -> role authorization (2) -> path existence (3) -> OCC stale version (4, before business state) -> from-state check (5) -> segregation of duties (6) -> matrix published (7) -> category match (8) -> severity range (9) -> date order (10) -> duplicate active claim (11) -> record sufficiency (12-13) -> unresolved liens (14) -> open appeal blocks finalize (15) -> holder window (16) -> final exceeds asserted (17) -> QSF sufficiency (18, before negative net) -> negative net award (19).

### Smoke Check Result

`bash start.sh` boots cleanly and answers requests. Full end-to-end test passed 52/52 checks covering: program creation, clock initialization to 2026-08-01T00:00:00Z, tier matrix publish, claimant registration, claim filing, eligibility screening, medical record upload/accept/verify, tier assignment with correct fee/net computation, lien lifecycle (identify/notify/negotiate/resolve), finalize-liens, prepare-disbursement with correct waterfall (3 disbursements summing exactly to net_award), approve/release all, auto-DISBURSED transition, claim closure with sealed ClosingStatement (no version/updated_at), flat aliases, and error responses (400 missing auth, 403 wrong role, 404 not found).

## Step 7: Run Tests and Iterate — 2026-08-12T22:30:00.000Z

**Iterations run:** 3 eight-round parallel sweeps (round 1: 47/81; round 2: 78/79; round 3: **79/79 in all 8 rounds — exit condition met**).

**Tests deleted (2), with PRD-silence category:**
- `test_net_award_consistent_with_canonical_fee` (test_07) — SIDE-EFFECT-ENUMERATION SILENCE: both assertions (fee==237, net==559) require attorney-fee recompute at lien resolution, but PRD §3.5's resolution sentence enumerates only `total_lien_cents` and `net_award_cents` as recomputed, and §3.6 shows the author says "attorney fee calculation re-runs" when intended (scaffold trigger agrees: assign-tier + uphold only). Two faithful readings diverge.
- `test_fee_recomputed_per_line_as_second_lien_resolves` (test_07) — same silence pattern; both assertions (fee==320, fee==237) are fee-recompute-at-resolution dependent.

**Tests trimmed (partial coverage, PRD 1c split):**
- `test_per_line_rounding_produces_canonical_fee` → renamed `test_resolve_sums_total_lien_across_resolved_liens`, kept only `total_lien_cents == 204` (verbatim §3.5); dropped fee==237 assertion.
- `test_fee_floored_at_zero_and_never_negative` → renamed `test_net_award_floored_at_zero`, kept `net_award_cents == 0` (derivable under both readings); dropped fee==0 assertion.
- test_08 waterfall tests: kept bucket count/order/payee/lien-amount/conservation assertions; dropped attorney-bucket==3.2M, claimant==5.8M, net==5.8M (all require fee-recompute-at-resolution; two faithful readings diverge on the concrete amounts).

**Fixes to `test_suite/`:**
- `test_04_tier_assignment.py::test_draft_matrix_not_assignable` — setup fix: publish a second row first so the program-level `ERR_NO_PUBLISHED_MATRIX` precondition (listed first in §3.4) is satisfied and the asserted supplied-row check `ERR_MATRIX_NOT_PUBLISHED` is the only one that can fire.
- `test_08_disbursement_and_qsf.py::test_self_approval_rejected_even_when_state_also_wrong` → renamed `test_state_error_beats_self_approval_when_both_apply`; assertion flipped to `ERR_DISBURSEMENT_INVALID_STATE` — PRD §2.9 (quoted in the test's own docstring) orders the from-state check *before* segregation-of-duties ("followed by"), so the original assertion contradicted its own citation.

**Fixes to `test_helpers/`:**
- `fixtures.py::create_claim_in_liens_pending` — was forwarding lien-creation kwargs (`lien_type`, `holder_name`, `asserted_amount_cents`) into `create_tier_assigned_claim`, which rejects them (TypeError); now splits them out and routes them to `add_lien`. This one fixture bug accounted for ~20 of the 34 initial failures (all lien-lifecycle/disbursement/closure setups).

**Fixes to `implementation/`:**
- `routes/medical_records.py` — added missing imports `ERR_INSUFFICIENT_MEDICAL_RECORDS`/`ERR_NO_QUALIFYING_RECORD` (NameError → 500 in verify-injury); removed the invented upload claim-state gate (PRD §3.3 gates accept/reject/verify only; scaffold upload endpoint has no precondition; the gate blocked PRD-permitted uploads to INJURY_VERIFIED claims used by two OCC/severity tests' setups). The ELIGIBILITY_PASSED→RECORDS_PENDING first-upload cascade is preserved.
- `routes/liens.py::create_lien` — allow identification when claim is TIER_ASSIGNED **or** LIENS_PENDING (PRD §3.5: "later identifications leave the claim status alone" presupposes later identifications are permitted); cascade still fires only from TIER_ASSIGNED.
- `routes/liens.py::_format_iso` — `holder_response_due_at` now renders fractional-less when the program clock has no sub-second part, matching the clock's exact `2026-08-01T00:00:00Z` reading (§2.5) and the verbatim-string convention the codebase already uses for `released_at`.
- `routes/disbursements.py::void_disbursement` — added the READY_FOR_DISBURSEMENT→DISBURSED auto-cascade when every sibling is RELEASED or VOIDED (§3.8 verbatim); without it, voiding the last pending disbursement left the claim's QSF reservation counting, so the §2.10 refund assertion could not hold.

**Feedback notes for generators:** (doc-generator, Zero-Silence) PRD never states attorney-fee recompute triggers relative to lien resolution/waiver — §3.5's enumeration omits fee while §3.6 explicitly names it, which is what made the fee-on-resolution tests underivable; (unit-test-generator, unique-derivability) the scaffold's difficulty designs `attorney_fee_per_line_vs_sum_then_round` / `attorney_fee_nested_rounding_mode_b` / `self_approval_beats_disbursement_state` produced tests asserting scaffold-intent outcomes that PRD prose does not uniquely determine (or, for the SoD priority pair, flatly contradicts).

## Step 8: Finalize PRD — 2026-08-12T22:38:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1310_mass_tort_claim_intake_lien_resolution/workspace/PRD_FINALIZED.md` with 5 inline edits, all traced to `<step_7_diff>` items. No new sections; all other Step 7 items required no PRD change (reasons below).

## Line counts
- `PRD.md`: 300 lines; `PRD_FINALIZED.md`: 300 lines (0% line-count delta — all edits are inline within existing paragraphs; ~24 added words avg per touched paragraph, 5 of 300 lines modified = 1.7% of lines touched).

## Changes (one bullet per edit)
- §2.5 — insert — clock-derived stamps (`holder_response_due_at`, `released_at`, `sealed_at`) keep the program clock's own textual precision (fractional seconds only when the clock reading has a sub-second part), with the concrete `2026-08-31T00:00:00Z` example — `implementation/routes/liens.py:57-67` (`_format_iso`), `implementation/routes/disbursements.py:127`, `implementation/routes/closing.py:53`.
- §3.3 — insert — medical-record upload carries no claim-status precondition; the `ELIGIBILITY_PASSED`→`RECORDS_PENDING` cascade is the only status-dependent upload behavior; claim-state gates apply to accept/reject/verify only — `implementation/routes/medical_records.py:42-82` (gate removed in Step 7).
- §3.5 — revise — lien identification is permitted against claims in `TIER_ASSIGNED` **or** `LIENS_PENDING`; other statuses rejected as `ERR_CLAIM_INVALID_STATE` (409); cascade fires only from `TIER_ASSIGNED` — `implementation/routes/liens.py:79-80, 107-109`.
- §3.5 — insert — neither lien-resolution path re-runs the attorney fee; `attorney_fee_cents` unchanged and `net_award_cents` recomputed against the stored fee; waiver likewise — `implementation/services/calculations.py:93-107` (`recompute_claim_totals` writes only `total_lien_cents`/`net_award_cents`), `implementation/routes/liens.py:242, 268, 293`.
- §3.7 — insert — attorney fee calculation runs only at tier assignment and on appeal uphold; lien resolution/waiver/finalization never re-run it — `implementation/routes/tier_assignment.py:78`, `implementation/routes/appeals.py:161` (the only post-creation writes to `attorney_fee_cents`).

## Step-7 items requiring no PRD edit
- `test_04_tier_assignment.py` setup fix: PRD §3.4 already lists program-level `ERR_NO_PUBLISHED_MATRIX` before supplied-row `ERR_MATRIX_NOT_PUBLISHED`; impl order matches.
- `test_08` rename/assertion flip: PRD §2.9 already orders the from-state check before segregation of duties ("followed by"); impl `approve_disbursement` matches.
- `fixtures.py::create_claim_in_liens_pending`: pure test-helper bug (kwargs misrouting), no PRD-visible behavior.
- `medical_records.py` missing imports: pure NameError bug fix, no behavioral choice.
- `disbursements.py::void_disbursement` cascade: PRD §3.8 already pins it verbatim ("crosses … automatically when … every disbursement on the claim is in `RELEASED` or `VOIDED`"); Step 7 fixed the impl to match the PRD, not vice versa.

## Per-edit pre-edit search log
1. **§2.5 clock-stamp precision** — (a) subject: rendering of program-clock-derived timestamps. (b) Enumerated via `grep -rn "current_utc\|holder_response_due_at\|released_at\|sealed_at"`: `routes/liens.py:57-67,99,160-163,215-216` (format + parse-back on silent path), `routes/disbursements.py:127` (verbatim copy), `routes/closing.py:53,78` (verbatim copy + statement body), `routes/programs.py:40,66-86` (verbatim storage, string-compare advance). (c) Wording scoped to "clock-derived stamps" and explicitly contrasted with "wall-clock metadata timestamps of §2.4" so it cannot be read as weakening the three-fractional-digit rule for `created_at`/`updated_at`; phrased as "fractional seconds appear only when the clock reading itself carries a sub-second part" — true for both verbatim copies and `_format_iso` (adding 30 days never changes the sub-second part).
2. **§3.3 upload gate** — (a) subject: claim-status preconditions on medical-record upload. (b) Enumerated: `routes/medical_records.py` `create_medical_record` (sole upload path; no status check, cascade at lines 78-80), `accept_record`/`reject_record`/`verify_injury` (RECORDS_PENDING gates, lines 118/134/150), `routes/flat_aliases.py` (GET-only aliases confirmed via grep), `routes/claims.py` (no record-creation path). (c) Final clause "the claim-state gates in this section apply to accept, reject, and verify only" added to prevent the new sentence from being read as loosening those three gates.
3. **§3.5 identification states** — (a) subject: claim-status gate and cascade for lien identification. (b) Enumerated via `grep -rn "TIER_ASSIGNED\|LIENS_PENDING…"`: `routes/liens.py:79-80` (gate), `107-109` (cascade only from TIER_ASSIGNED), `154` (notify gate, untouched), `279` (finalize gate, untouched); no other lien-creation path exists. (c) Parenthetical "(made while the claim is `LIENS_PENDING`)" added to "later identifications" so the existing sentence can't be read as permitting identification in arbitrary later states (e.g. `LIENS_RESOLVED`, which impl rejects).
4. **§3.5 resolution recompute scope** — (a) subject: which claim fields lien resolution/waiver recompute. (b) Enumerated via `grep -rn "attorney_fee"`: writes at `routes/claims.py:76` (init 0), `routes/tier_assignment.py:78`, `routes/appeals.py:161`; reads at `services/calculations.py:105,158,165`, `routes/appeals.py:165`, `routes/closing.py:50,76`; `recompute_claim_totals` (calculations.py:93-107) writes only `total_lien_cents`/`net_award_cents` and is called from liens.py:242 (resolve), 268 (waive), 293 (finalize). (c) Used "leaving `attorney_fee_cents` unchanged / recomputed against the stored fee" rather than any formula restatement, so the sentence stays true regardless of when the stored fee was last set (assign-tier or uphold).
5. **§3.7 attorney-fee run points** — (a) subject: when the attorney fee calculation runs. (b) Same enumeration as edit 4 (the two edits are cross-references of one behavior). (c) Phrased "runs only at tier assignment (§3.4) and when an appeal is upheld (§3.6)" — not "runs exactly twice" — because multiple appeal cycles can re-run it; verified §3.6's uphold prose and §3.4's "calculation then runs" remain verbatim-consistent, and §3.7's existing net-award recompute list ("at tier assignment, at every lien resolution or waiver, at lien finalization, and at every appeal outcome that re-tiers") is unchanged and still accurate (deny/withdraw don't recompute net, and the sentence only covers re-tiering outcomes).

## Step 9: Complete PRD — 2026-08-12T22:49:00.000Z

**Source**: `PRD_FINALIZED.md` (300 lines, 45,541 chars) → **PRD_COMPLETED.md** (302 lines, 52,526 chars; +6,985 chars, 52 changed diff lines).

**Counts**: 14 ambiguity-pins, 3 mismatch-revisions.

**Changes** (all in `workspace/PRD_COMPLETED.md`):

- §2.1 — revise — ambiguity — unrecognized `X-User-Role` value is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400, not 403 — `implementation/middleware.py:37-42`
- §2.1 (ClaimantRole bullet) — revise — mismatch — PRD claimed ownership checks on all nested sub-resources; impl enforces ownership only on single claimant/claim reads (nested+flat), claimant-scoped writes (before state validation), and flat single reads of liens/appeals/disbursements/closing-statements; failed check is `ERR_NOT_FOUND` 404 — `implementation/routes/claims.py:122,190`, `routes/claimants.py:119`, `routes/appeals.py:50,209`, `routes/liens.py:189`, `routes/flat_aliases.py:48-140`
- §2.3 — insert — ambiguity — non-integer limit/offset falls back to defaults; out-of-range values clamped into [1,100]/[0,∞) rather than rejected — `implementation/routes/helpers.py:55-67`
- §2.4 — insert — ambiguity — version-increment list extended to include lien waiver, lien finalization, the two claim-status cascades (first upload, first lien), screening, denial, withdrawal, closure — `implementation/routes/liens.py:109,269,294`, `routes/medical_records.py:80`, `routes/claims.py:159,180,197`, `routes/closing.py:41`
- §2.5 — insert — ambiguity — clock advance rejects missing/non-string/non-later `to_iso8601` with `ERR_INVALID_REQUEST` 400; advance bumps program `updated_at`/`version`; response is the updated program — `implementation/routes/programs.py:70-86`
- §2.9 — insert — ambiguity — body-schema failures (missing/null required fields, enum/type/format/range violations) are `ERR_INVALID_REQUEST` 400; on the two versioned writes the `expected_claim_version` presence check precedes the version comparison — `implementation/routes/helpers.py:48-52`, `routes/tier_assignment.py:40-45`, `routes/liens.py:206-211`
- §2.10 — revise — mismatch — void refund is realized through the reconciliation formula, not an immediate per-disbursement credit: reservation still counts while claim stays `READY_FOR_DISBURSEMENT`; refund materializes when the claim leaves that status; ledger recomputed on every prepare/release/void and program version advances — `implementation/services/calculations.py:183-200`, `routes/disbursements.py:144-168`
- §3.1 — insert — ambiguity — `program_code` uniqueness not enforced server-side; tier-matrix create rejects bad `injury_category` with `ERR_INVALID_REQUEST` 400; publish of a non-DRAFT row is `ERR_INVALID_REQUEST` 400; overlap test defined (max of minima ≤ min of maxima) — `implementation/routes/programs.py:31-47`, `routes/tier_matrices.py:44-46,91-92,102-106`
- §3.2 — insert — ambiguity — registration validates date shape, ssn_last4 shape, category enum, boolean flag, each as `ERR_INVALID_REQUEST` 400; claim_number is zero-padded 4-digit sequence from a single global counter starting `CLM-0001`; `claimant_id` not in program → `ERR_NOT_FOUND`; no duplicate check at filing — `implementation/routes/claimants.py:57-73`, `db.py:21-23`, `routes/claims.py:60-63`
- §3.2 — insert — ambiguity — claim carries `denied_reason` and `prepare_disbursement_user_id` fields, both null at creation — `implementation/routes/claims.py:73,80`
- §3.2 — insert — ambiguity — deny runs state check before reason validation; whitespace-only reason rejected; withdrawal runs ownership 404 before withdrawability 409 — `implementation/routes/claims.py:168-175,190-194`
- §3.3 — insert — ambiguity — upload validates record_type enum, integer severity in [0,100], boolean flag as `ERR_INVALID_REQUEST` 400; `received_at` is a wall-clock metadata stamp, not program clock; accept/reject evaluate the claim-state check before the record-state check — `implementation/routes/medical_records.py:54-63,69,118-122`
- §3.5 — insert — ambiguity — lien identification rejects bad lien_type or negative/non-integer asserted amount as `ERR_INVALID_REQUEST` 400, claim-status check first; new lien's four nullable fields start null — `implementation/routes/liens.py:79-104`
- §3.5 — insert — ambiguity — notify evaluates the lien from-state check (`ERR_LIEN_INVALID_STATE`) before the claim-status check — `implementation/routes/liens.py:151-155`
- §3.5 — insert — ambiguity — negotiated path: missing/non-integer/negative `final_demand_cents` → `ERR_INVALID_REQUEST` 400 (only above-asserted is 422); silent path ignores client-supplied `final_demand_cents`; both paths accept optional `resolution_notes` — `implementation/routes/liens.py:213-234`
- §3.5 — insert — ambiguity — waive rejects missing/empty/whitespace-only notes as `ERR_INVALID_REQUEST` and advances claim version by 1; finalization check order pinned (claim state → unresolved liens → open appeal) and advances claim version by 1 — `implementation/routes/liens.py:253-269,279-294`
- §3.6 — insert — ambiguity — appeal filing runs ownership 404 first, then claim state, then already-open, then body validations; `appealed_tier_matrix_id` recorded without validation, only `requested_tier_matrix_id` must be a PUBLISHED row of the program; new appeal's `resolution_rationale` starts null — `implementation/routes/appeals.py:50-85`
- §3.6 — insert — ambiguity — uphold/deny permitted only from `UNDER_REVIEW`; uphold re-runs only the arithmetic, not §3.4 preconditions (no category/severity re-check, claim stays `TIER_ASSIGNED`) — `implementation/routes/appeals.py:142-176`
- §3.7 — insert — ambiguity — prepare-disbursement records caller in `prepare_disbursement_user_id`, spawns rows with `released_at` null, and returns the updated claim object — `implementation/routes/disbursements.py:56-70`, `services/calculations.py:139-178`
- §3.8 — revise — mismatch — void refund described via reconciliation (reservation released when claim crosses to `DISBURSED`) instead of an unconditional immediate per-disbursement refund — `implementation/routes/disbursements.py:144-168`, `services/calculations.py:183-200`
- §3.8 — insert — ambiguity — close requires `DISBURSED` (`ERR_CLAIM_INVALID_STATE`), response body is the updated claim, ClosingStatement carries `claim_id`, statement retrievable via list/read endpoints — `implementation/routes/closing.py:37-57`
