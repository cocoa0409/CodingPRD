# Worklog — task_2614_charitable_solicitation_registration

## Step 1: Create task directory — 2026-09-03T20:05:01.490Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2614_charitable_solicitation_registration` and `.../workspace`. Index 2614 was pre-assigned by the orchestrating command (no auto-allocation scan, per concurrency constraint).

## Step 2: Generate scaffold — 2026-09-03T21:38:21.492Z

All three artifacts are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2614_charitable_solicitation_registration/`)
- `SCAFFOLD.yaml` — 2921 lines / 137 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1739 lines / 125 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3291 lines / 223 KB

**SCAFFOLD.yaml (§1.0–§1.7):** `api_prefix: "/"`, 14 entities, 6 state machines + 2 derived Organization posture dimensions, 2 OCC concurrency rules, 12 calculations, 35 ordered validations, **49 endpoints**, 43 error codes, 5 roles. Profile: `compliance_audit` / `temporal_windowing`, graph topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`.

**§1.8 (`scaffold_difficulty_design`):** 9 rules / **21 instances** — dual-variant divergence, ordering-sensitive rounding and clamping, cyclic revision/escalation loops, 3-level cascades (E1/E2/E3 and R1/R2/R3), three priority-pair conflicts, five boundary cases, two conservation invariants.

**§1.9 (`scaffold_corner_design`):** **9 sections / 85 instances** (66 with full `test_recipe`, 19 excluded stubs each citing a real §1.8 instance) — entities 15, state_machines 12, calculations 12, validations 13, endpoints 6, errors 14, rbac 5, cross_cutting_layers 6, consistency_model 2.

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (762 calls scanned).
- All 43 §1.6 error codes are asserted by at least one recipe; all 49 §1.5 endpoints are exercised; all 14 entities appear in asserts; no duplicate instance names across the two design files; no stub carries a `test_recipe`; no forbidden concurrency vocabulary.

**Design adjudications**
- `api_prefix: "/"` so §1.5 paths satisfy the linter's FK reverse-reachability check.
- Widened the APPROVE precondition to `status IN {REGISTERED, DELINQUENT}` for supersede targets.
- Fixed an internal contradiction: `ERR_CONTRACT_FILING_WINDOW_CLOSED` said "30 days" against `CONTRACT_FILING_HARD_STOP_DAYS: 60`; the condition now references the constant.
- Replaced a non-enum `basis: IRS_EXTENSION_FILED` with `IRS_990_EXTENSION` and aligned an NY `audit_threshold_cents`.
- Two recipes were re-planned around scaffold semantics rather than asserting a guess: the superseded-statement error uses an explicit stale `financial_statement_id` on a fresh filing (cascade R2 would otherwise silently repoint an open filing), and `ERR_FILING_POSTURE_DELINQUENT` is triggered on a separate pre-sweep DRAFT NV filing so only priority 31 can fire.
- Added two error triggers late (`ERR_ASSURANCE_LEVEL_INSUFFICIENT`, `ERR_DUPLICATE_STATE_REGISTRATION`) after an audit showed both were only ever the *losing* rule in priority-pair instances; the duplicate case uses a DRAFT predecessor so the overlap rule at priority 22 (which only sees SUBMITTED/REGISTERED/DELINQUENT/CEASED) cannot pre-empt priority 27. Two stub rationales that overclaimed §1.8 coverage were corrected at the same time.
- YAML: `"limit?"`-style keys and `"$.data[0].id"` JSONPaths are quoted inside flow collections to keep PyYAML parsing.

## Step 3: Copy shared files — 2026-09-03T21:38:37.155Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T21:52:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **439 lines / 108 KB**, written via 9 chunked appends (no truncation). Final heading is `## 5. Error Code Catalogue`, ending on the last error-table row (`ERR_DUPLICATE_IDENTIFIER | 409 Conflict`) — a real section boundary, with no audit footer inside the file.

**Structure** (domain-derived, not copied from the example): §1 three-paragraph introduction; §2 with 12 subsections (2.1 Actors & RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Monetary Precision/Ratios/Whole-Day Arithmetic, 2.7 State Profiles as Configuration Backbone, 2.8 Two Independent Posture Dimensions, 2.9 Resolving Path & Payload References, 2.10 OCC on Superseding Writes, 2.11 Order of Validation, 2.12 Conserved Quantities); §3 with 9 workflow subsections organized as a compliance timeline (onboarding/footprint -> statements & assurance -> filing/deadlines/fees -> certification & adjudication -> extensions -> fundraiser registry & contracts -> co-venture settlement -> disclosure language -> sweep & enforcement); §4 49-endpoint table (4 columns); §5 43-error table (2 columns).

**Hard Contract reports**

Field coverage check: entities[].fields 124/124; endpoints[].request_body/input 101/101; query_params all present; path_params 2/2; deduplicated required set 135 names all present as exact backtick tokens. Status: PASS

Rule coverage check: 35/35 validations expressed as an explicit ordered ladder with applies_to endpoint sets (§2.11); 2/2 OCC rejections expressed (expected_registration_version / expected_organization_version + ERR_STALE_*_VERSION + 412); 46/46 state-machine transitions fully expressed with preconditions paired to error ids and every cascade link (L1–L3, D1–D3, E1–E3, C1–C2, F1–F3, R1–R3); 12/12 calculations in operator-free prose with constants embedded and pinned evaluation/rounding order (incl. three worked examples making rounding order observable); all 43 errors[].id mentioned outside §5; 49/49 endpoints' side effects expressed in the owning workflow narrative; 124/124 entity field defaults/enums/ranges reconstructible from prose; 14/14 sibling-branch symmetry groups with equal prose density. Status: PASS

Path purity check (§3 only): 922 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Status: PASS

Additional checks: §2.2 byte-identical to `section-2.2-response-structure.md`; zero pseudocode operators; zero fuzzy hedges; §3 has no bullet lists, no schema tables, no declared foreign keys. The two withheld design files were not opened; no sibling task directory read.

Two authority conflicts between the scaffold's `validations[]` table and looser `errors[].condition` prose were resolved in favour of the priority-ordered `validations[]` table: `ERR_FILING_POSTURE_DELINQUENT` documented as guarding extension-request creation only, and `ERR_SOLICITATION_RESTRICTED` as guarding promotion activation only.

**Orchestrator truncation guard:** verified independently — `wc -l` = 439, tail ends on a complete table row, `## ` headings 1–5 all present, and the Step 2 difficulty instruction ("harder than expert level") does not appear anywhere in PRD.md.

## Step 6: Generate implementation — 2026-09-03T22:35:00.000Z

Implementation complete and verified.

Files under `workspace/implementation/`: app.py 57, auth.py 90, clock.py 34, dates.py 82, db.py 104, errors.py 104, money.py 31, response.py 127, validate.py 273, services/calc.py 315, services/cascades.py 378, services/derive.py 170, routes/config.py 99, routes/organizations.py 351, routes/registrations.py 448, routes/fundraisers.py 212, routes/promotions.py 245, routes/enforcement.py 153, start.sh 10 (executable, `exec python3 app.py`), requirements.txt 1 (`flask>=2.0`). 3284 lines total; `python3 -m py_compile` clean on all 21 .py files.

Coverage: **49/49 endpoints** (method+path diffed against PRD §4 — exact match, no extras/gaps). **43/43 errors** defined and each actually raised; all HTTP statuses cross-checked against §5 — zero mismatches. Storage in-memory only; fresh boot verified empty (`total_count: 0` on all 6 collections) with clock at documented default. No seeding, no disk, no /tmp.

Verification: four smoke suites against a live server — auth 401 / RBAC 403 / duplicate 409 / OCC 412 / pagination 422; full DRAFT→SUBMITTED→DEFICIENT→REGISTERED loop with `deficiency_round_count` incrementing and documents flipping to REJECTED; restatement cascade (statement SUPERSEDED, attestation re-derived to AUDIT, filing knocked to DEFICIENT); segregation-of-duties on submit and promotion settle; delinquency sweep (penalty 50000 capped, `filing_posture` DELINQUENT); `ERR_CURE_WINDOW_EXPIRED` then the full E1/E2/E3 chain (CEASED → `ceased_state_codes` → `solicitation_posture` RESTRICTED → promotion HALTED), second state → HALTED, then vacate restoring CEASED→REGISTERED and zeroing the ledger; contract FILED vs LATE_FILED (surcharge 10000) vs closed-window 422; disclosure clause re-resolution. All 35 GET shapes swept for 5xx — none. PRD worked examples reproduced exactly: deadline 2025-12-31→2026-04-30→2026-05-15, filing fee 5250, penalty 29000/10 months, settlement 30500 on an 18000 subtotal, co-venture projection 750000 vs settlement 500000. Smoke servers killed by PID; no broad pkill.

PRD ambiguities resolved (judgement calls):
1. Ladder slots for unnamed checks: withdraw blocked by live enforcement action → `ERR_INVALID_REGISTRATION_STATE` after rung-9 status check; extension GRANT against a filing outside {DRAFT, SUBMITTED, DEFICIENT, REGISTERED} → `ERR_INVALID_REGISTRATION_STATE` before rung 30; enforcement CURE with `settlement_total_cents == 0` → `ERR_INVALID_ENFORCEMENT_STATE`; ESCALATE against a filing outside {DELINQUENT, CEASED} → `ERR_INVALID_REGISTRATION_STATE` between rungs 10 and 25.
2. Prose vs ladder on promotion filing: §3.7 prose puts window before fundraiser-registration; the ladder puts registration at rung 19 and window at rung 26. Followed the **ladder** (§2.11 declares it authoritative).
3. Version-bump collapsing: `touch_once` = one increment per row per request for cascade links; `Organization.version` moves only where PRD names it. The sweep opts out (`once=False`) so the organization increments once per delinquent candidate, matching §3.9's per-candidate wording.
4. `RENEWAL` without `supersedes_registration_id` is accepted (no error named); `supersedes_registration_id` on an `INITIAL` is `ERR_INVALID_REQUEST`.
5. PATCH /organizations: `ein` or `domicile_state_code` in body → `ERR_INVALID_REQUEST` (immutable); deadline-recompute cascade fires only when `fiscal_year_end_month` actually changes.
6. `included_clauses` optional on a disclosure statement, defaulting to `[]`.
7. Clock discipline: `created_at`/`updated_at` and every stamped business timestamp take the logical clock; only `meta.api_request_timestamp` uses wall time.
8. Sweep narrowing: a supplied `state_code` filters both passes; pass 1 (delinquency) compares strictly-before the effective due date, pass 2 (fundraiser lapse) at-or-before expiry, inclusive.

## Step 5: Generate unit tests — 2026-09-03T23:15:00.000Z

Test generation complete. Both output directories live at the task root, not under `workspace/`.

**`test_helpers/`** (2,022 lines): `__init__.py` 37, `api_client.py` 325, `api_errors.py` 102, `assertions.py` 395, `constants.py` 71, `factories.py` 290, `fixtures.py` 638, `test_users.py` 66, `types.py` 498.

**`test_suite/`** (6,370 lines, 16 test files + conftest): conftest.py 49; test_01_assurance_and_fee_derivation 336 (A); test_02_coventure_benefit_and_settlement 301 (A); test_03_penalty_accrual_and_settlement 301 (A); test_04_filing_revision_and_enforcement_cycles 250 (A); test_05_cascades 219 (A); test_06_filing_conflict_precedence 403 (A); test_07_cross_entity_gates 270 (A); test_08_conserved_quantities 251 (A); test_09_entity_surface 931 (B entities 15); test_10_filing_and_enforcement_state_machines 465 (B state_machines 9); test_11_derived_amounts_and_deadlines 387 (B calculations 6); test_12_gates_on_submission_registry_and_contracts 381 (B validations 8); test_13_endpoint_surface 227 (B endpoints 4); test_14_error_catalog 583 (B errors 13); test_15_role_and_ownership_boundaries 246 (B rbac 5); test_16_concurrency_triggers_and_consistency 370 (B cross_cutting_layers 4 + consistency_model 2).

Instance → test mapping:
- Queue A (Difficulty, §1.8): **21/21 instances → 47 tagged tests**. All 21 non-stub; several have 2–3 tests splitting distinct assertions (rounding order, ledger conservation, aggregate untouched-ness).
- Queue B (Corner, §1.9): **66/66 live instances → 71 tagged tests**. The 19 `excluded_because:` stubs deliberately not translated.
- Total: **118 test functions, 120 collected items** (one 3-case parametrize in test_03).

Skipped instances: **none** — every non-stub instance passed the PRD-first two-condition filter.

Verification: tag audit against both yamls (`MISSING corner: []`, `MISSING difficulty: []`, `STRAY: []`); AST audit of all 118 tests (each has a docstring with exactly one `Design:` line as the last non-blank line, no docstring mentions "scaffold" or a §1.x reference); `py_compile` clean on all 26 .py files; `pyflakes test_suite/*.py` clean apart from intentional `# noqa` barrel re-exports; `pytest --collect-only -q` collects 120 tests with no import/collection errors. Nothing under `workspace/implementation/` was read or written; no sibling task directory touched.

PRD-fidelity note from the generator: test_16's two version-guard tests exercise the only two version-guarded creates in the contract (`POST /financial-statements` and `POST /extension-requests`, PRD §2.10); the second deliberately requests 60 days against a 90-day cap so only the 412 stale-token rung can fire (the PRD enforces `extension_max_days` at grant time, so a larger request would have made the failing rung ambiguous).

**Orchestrator note:** Steps 5 and 6 were launched in two consecutive messages rather than one, so the impl generator did not get physical isolation from `test_suite/`. Mitigated by an explicit absolute prohibition in the Step 6 prompt against reading/listing/globbing `test_helpers/` or `test_suite/`; the impl agent's own report confirms it read only INSTRUCTION.md, SCAFFOLD.yaml and PRD.md, and at the time it started neither test directory existed on disk yet.

## Step 7: Run tests and iterate — 2026-09-03T23:25:00.000Z

All 8 rounds green: 120/120 each.

**Iterations run:** 2 (one diagnostic sweep with 9 deterministic failures, one clean sweep after fixes).

**Tests deleted:** None. Every failing test's asserted rule was verbatim-covered by PRD; all nine failures traced to test-artifact bugs (wrong envelope unwrap, missing auth headers, or setup preconditions PRD does not license). One *assertion* was removed under STEP 1c partial-coverage handling (see below).

**Fixes applied to `test_suite/`:**
- `test_07_cross_entity_gates.py` — `_first_action_for()` passed `None` as the headers argument to `api_client.list_enforcement_actions`, so the setup GET arrived unauthenticated (401 `ERR_UNAUTHENTICATED`). Now passes `COMPLIANCE` (PRD §4 lists ComplianceOfficer on `GET /enforcement-actions`). Identical helper in test_06 already did this correctly.
- `test_07_cross_entity_gates.py` — `test_a_cease_order_in_another_state_restricts_activation_without_halting_it` called `api_client.activate_coventure_promotion(id)` with no headers, so it got 401 instead of the asserted `ERR_SOLICITATION_RESTRICTED`. Now uses the `activate_promotion` fixture (ComplianceOfficer headers).
- `test_06_filing_conflict_precedence.py` — `_voided_contract()` did `validate_success(...)["data"]`; `validate_success` already returns the unwrapped `data`, so this raised `KeyError: 'data'` and broke both tests in the class. Double-unwrap removed (only occurrence in the suite).
- `test_06_filing_conflict_precedence.py` — `test_once_the_halt_is_lifted_the_same_packet_reports_its_assurance_shortfall` issued `CURE` directly against an `ESCALATED` action. PRD §3.9: "A `CURE` decision is available only from `REMEDIATION_SUBMITTED`", and remediation "is available from `OPEN` and from `ESCALATED`". Added the intervening `remediate_action` so the escalated order re-enters remediation first; the implementation's 409 `ERR_INVALID_ENFORCEMENT_STATE` was PRD-correct.
- `test_09_entity_surface.py` — `test_the_two_expense_figures_are_derived_from_the_three_expense_inputs` asserted `Organization.version == 2` after a plain (non-restatement) statement create. PRD §3.2 names the org-version bump only for the restating write; §2.8 names it only for posture recomputation. Uncovered assertion removed (STEP 1c); the two covered derivation assertions and the `CURRENT` status assertion kept.
- `test_16_concurrency_triggers_and_consistency.py` — `TestStaleOrganizationToken`: setup assumed the first statement create advances `Organization.version`, which PRD does not state, so the second create's token was never stale. Setup now advances the version with a `PATCH /organizations` amendment (unambiguously a mutation of that row per §2.5) and spends the pre-amendment token, so rung 8 fires. All "the refused create filed nothing" assertions preserved.
- `test_16_concurrency_triggers_and_consistency.py` — `TestStaleRegistrationToken`: setup assumed creating a first `PENDING` extension request bumps the filing's version. PRD §3.5 bumps the filing only when superseding a `GRANTED` request or on a grant. Setup now `GRANT`s the first request (§3.5: the grant "increments" the filing's `version`), which is also the exact silent-deadline-destruction scenario the OCC guard exists for; assertions updated to `GRANTED` / non-null `extended_due_date` / `effective_due_date == extended_due_date`.
- `test_16_concurrency_triggers_and_consistency.py` — `TestOrganizationVersionAdvancesOnChildWritesToo`: asserted a third version bump from a plain statement create. Reworked to make the third bump a **restatement**, the one child write PRD §3.2 explicitly says increments `Organization.version` by one; asserts a delta of exactly one across the restatement plus the prior statement moving to `SUPERSEDED`.

**Fixes applied to `test_helpers/`:** None needed — no shared fixture/factory/assertion was at fault.

**Fixes applied to `implementation/`:** **None.** All nine failures were test-artifact defects; in every case the implementation's behavior was the PRD-faithful one (notably the `CURE`-from-`ESCALATED` rejection and the absence of an org-version bump on a non-restating statement create). No PRD-required check was weakened or removed.

**Final sweep evidence:** `results.1.json` … `results.8.json`: 120/120 passed, 0 failed, 0 errors in every round (each ~209 s wall).

**Orchestrator independent verification:** all 8 `results.*.json` exist (~40 KB each, timestamped 23:23) and parse to `passed=120 failed=0 total=120 errors=0`. Sweep artifacts confirmed present, not merely claimed.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 8 `test_suite/` fixes (one of them an assertion removal under STEP 1c). The skip condition requires zero iterations beyond the baseline, so Step 8 runs — with `<step_7_diff>` containing 0 `implementation/` fixes and 0 deletions, which bounds it tightly to the PRD-silence sites the test fixes exposed (org-version bump semantics on child writes, `CURE` reachability from `ESCALATED`, extension-request version bumps).

## Step 8: Finalize PRD — 2026-09-03T23:30:00.000Z

PRD_FINALIZED.md written: two sentence-level inserts, nothing else.

**Line counts:** PRD.md 439 → PRD_FINALIZED.md 439 (0.00% line delta; 2 of 439 lines revised = 0.46% of lines touched). File still ends at the same real boundary — the §5 error-catalogue table, final row `ERR_DUPLICATE_IDENTIFIER`.

**Changes**
- §3.2 — insert — after "The restating write also increments `Organization.version` by one.", pinned that a *non-restating* statement create (a fiscal year with no `CURRENT` statement of its own) runs none of the three links and leaves `Organization.version` and every registration untouched — `routes/organizations.py:318-319` (`if apply_restatement(statement): touch_once(organization, ...)`), `services/cascades.py:88-94` (returns `False` when no prior `CURRENT` statement for that org+fiscal_year).
- §3.5 — insert — after "Superseding a `PENDING` request has no effect on the deadline…", pinned that a create superseding no `GRANTED` request (empty history or a `PENDING`-only history) leaves the filing row untouched, `version` included — `services/cascades.py:162-175` (registration touched only when `superseded_granted`), `routes/registrations.py:397-409` (create path never touches the filing otherwise).

**Per-edit pre-edit search log**

Edit 1 (§3.2)
- (a) Subject: which writes mutate the `Organization` row / bump `Organization.version`, specifically the `POST /financial-statements` path and the restatement cascade's reach into registrations.
- (b) Enumerated/read: `grep -rn "touch_once(organization|recompute_organization|touch(organization|apply_restatement"` across `implementation/` — every org-row writer: `routes/organizations.py:121` (PATCH amendment, unconditional touch), `:318-319` (restatement only), `services/derive.py:59-77` (`recompute_organization`, `once` variant), `services/cascades.py:148` (approve L3), `:209` (escalate E2, conditional on filing `DELINQUENT`), `:232` (cure), `:252` (vacate), `:338` (sweep D2, `once=False`), `routes/enforcement.py:43` (issuance), `routes/registrations.py:306` (withdraw, `REGISTERED` variant only). Also confirmed `routes/promotions.py`, `routes/fundraisers.py`, officer-disclosure/solicitation-activity/registration/document creates never touch the org row, and `cascades.py:96-118` for exactly which registrations a restatement touches.
- (c) Adjustment: scoped the sentence to the statement-create path only ("A create that is not a restatement") rather than a general claim about child writes, so the amendment/approval/sweep/cure/vacate/escalate/issuance org-version bumps elsewhere are not narrowed or contradicted; phrased the trigger as "a fiscal year that has no `CURRENT` statement of its own" to mirror the impl's org+fiscal_year+`CURRENT` prior filter.

Edit 2 (§3.5)
- (a) Subject: which writes bump a `StateRegistration.version`, specifically `POST /extension-requests` and the supersession helper.
- (b) Enumerated/read: `grep -rn "touch_once(registration"` — `routes/registrations.py:236` (submit), `:275` (review DEFICIENT), `:303` (withdraw), `:441` (extension GRANT), `services/cascades.py:117` (restatement repoint), `:133` (approve), `:174` (supersede of a GRANTED request), `:207` (escalate E1), `:230` (cure restore), `:250` (vacate restore), `:327` (sweep delinquency); plus `routes/registrations.py:370-409` (create path: OCC check, rungs 30/31, `supersede_extension_history`, `stamp_new` — no filing touch) and `routes/organizations.py:123-130` (fye amendment recompute).
- (c) Adjustment: rewrote the claim from "superseding a `PENDING` request" to "a create that supersedes no `GRANTED` request", explicitly covering both the empty-history and `PENDING`-only cases, so a history containing a `GRANTED` request is still governed by the following (unchanged) sentence; said "leaves the filing row itself untouched" rather than naming individual fields, so the deadline-recompute paths on grant/supersede-of-granted are not misdescribed.

Not edited (verified PRD already determines the behavior, prose kept verbatim): the `CURE`-only-from-`REMEDIATION_SUBMITTED` reachability item (§3.9 states it, `routes/enforcement.py:85-95` matches, 409 `ERR_INVALID_ENFORCEMENT_STATE` per §2.11 rung 10); the `PATCH /organizations` version bump used in the reworked test setups (§2.5's every-mutation rule plus `routes/organizations.py:121`); and the four pure test-artifact fixes (missing auth headers in test_07, double envelope unwrap in test_06) which carry no PRD-silence content.

**Orchestrator independent verification:** `diff PRD.md PRD_FINALIZED.md` yields exactly 4 changed lines (2 revised lines, `207c207` and `257c257`) — both pure in-paragraph sentence inserts, no new sections, no deletions, same 439-line length, same trailing section boundary.

## Step 9: Complete PRD — 2026-09-04T00:05:00.000Z

Run as **three sequential file-partitioned passes** over the same `workspace/PRD_COMPLETED.md`, to avoid the known failure mode where a single-agent full-impl scan silently produces a file byte-identical to its source. Partition: pass 1 = `routes/organizations.py` + `routes/registrations.py` + `routes/config.py`; pass 2 = `routes/fundraisers.py` + `routes/promotions.py` + `routes/enforcement.py`; pass 3 = `services/calc.py` + `services/cascades.py` + `services/derive.py` + the 9 top-level modules (app/auth/clock/dates/db/errors/money/response/validate).

**Totals:** PRD_FINALIZED.md 439 lines / 108,865 chars → PRD_COMPLETED.md **441 lines / 121,756 chars** (+2 lines, +12,891 chars). The +2 lines are one paragraph split inside the existing §2.3; every other edit is in-paragraph. No new sections. File still ends at §5 with final row `ERR_DUPLICATE_IDENTIFIER`.

**Counts:** 45 changes total — **39 ambiguity-pins, 6 mismatch-revisions** (pass 1: 13 + 3; pass 2: 18 + 2; pass 3: 8 + 1).

### Pass 1 (organizations / registrations / config) — 16 changes
- §2.5 — insert — ambiguity — a row driven by several links of one cascade in a single request advances `version` by exactly one for the request as a whole, not once per link; the sweep is the sole exception (org row advances once per swept registration) — `db.py:71-88`, `services/derive.py:59-77`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, non-integer/negative `offset` → `ERR_INVALID_REQUEST`; filter params are exact-match and an unrecognised value selects nothing (`total_count` 0) — `response.py:75-116`
- §2.7 — insert — ambiguity — every optional profile integer (and `late_fee_escalation_pct`) floored at zero; `disclosure_required_clauses` restricted to the canonical five, stored deduplicated in canonical order — `routes/config.py:44-68,77-79`
- §3.1 — revise — mismatch — the FYE-amendment cascade recomputes `extended_due_date` too, fires only when the supplied month actually differs, walks filings in `created_at` order, re-derives nothing else — `routes/organizations.py:118-131`, `services/calc.py:77-95`
- §3.1 — insert — ambiguity — amendable fields optional, a null value ignored rather than clearing; the amendment always increments `Organization.version` even when nothing moved; naming `ein`/`domicile_state_code` at all → `ERR_INVALID_REQUEST` — `routes/organizations.py:102-121`
- §3.1 — insert — mismatch — PATCH `/organizations/{id}` resolves organization existence *before* payload shape, an explicit exception to the §2.11 ladder — `routes/organizations.py:100-101`
- §3.1 — insert — ambiguity — `channels` stored/echoed in request order with duplicates preserved — `routes/organizations.py:248,262`
- §3.1 — insert — ambiguity — `officer_name` 1–200 chars, not blank — `routes/organizations.py:329`
- §3.1 — insert — ambiguity — `is_certifying_officer` filter truthy-parsed (`true`/`1`/`yes`, trimmed+lower-cased); every other value selects the false side — `routes/organizations.py:214-217`
- §3.2 — insert — ambiguity — `total_revenue_cents` and `contributions_cents` may not be negative — `routes/organizations.py:278-279`
- §3.3 — insert — ambiguity — `supersedes_registration_id` optional on a `RENEWAL` too — `routes/registrations.py:94-101`
- §3.3 — insert — ambiguity — creation derives `required_financial_attestation`, `renewal_due_date`, `effective_due_date`, `filing_fee_cents`; `extended_due_date` null — `routes/registrations.py:152-156`
- §3.3 — insert — ambiguity — `prepared_by_officer_id` need only exist (may belong to another organization); `doc_type` carries no uniqueness rule — `routes/registrations.py:333-334`
- §3.3 — insert — ambiguity — calendar `next_effective_due_date` is the smallest date strictly after the clock (null when none), `delinquent_state_codes` distinct+ascending, entries of every status included, both extras honour the `fiscal_year` filter — `routes/organizations.py:144-173`
- §3.4 — insert/revise — ambiguity + mismatch — `certification_note` validated but never persisted; `APPROVE` accepts every document whatever its prior `review_status`; one whole-row organization recomputation incrementing `Organization.version` by exactly one; `deficiency_reasons` elements must be strings and are free-form — `routes/registrations.py:187,248`, `services/cascades.py:124-149`
- §3.4 — insert — ambiguity — `withdraw_reason` must be non-blank; the live-enforcement refusal is `ERR_INVALID_REGISTRATION_STATE` just after the status gate; the `DRAFT` variant leaves the organization row untouched including `version` — `routes/registrations.py:285-307`
- §3.5 — insert — ambiguity — a `GRANT` against a non-grantable filing status reports `ERR_INVALID_REGISTRATION_STATE`, ahead of the extension-allowed re-check — `routes/registrations.py:428-433`

### Pass 2 (fundraisers / promotions / enforcement) — 20 changes
- §2.11 rung 16 — revise — mismatch — rung 16 claimed segregation-of-duties applies only to filing submission; added the promotion-settlement limb and endpoint — `routes/promotions.py:166-174`
- §3.6 — insert — ambiguity — `legal_name` 1–200 chars, not blank — `routes/fundraisers.py:33`
- §3.6 — insert — ambiguity — all four registration payload fields required; `bond_on_file_cents` non-negative — `routes/fundraisers.py:76-79`
- §3.6 — insert — ambiguity — contract `state_codes` elements must be strings naming existing profiles; array stored/echoed verbatim — `routes/fundraisers.py:118,141`
- §3.7 — insert — ambiguity — `coventurer_id` may name any registry firm regardless of `fundraiser_type`; `state_codes` echoed verbatim — `routes/promotions.py:67,78`
- §3.7 — insert — ambiguity — the window-conflict check is scoped to the co-venturer alone, never narrowed to the benefiting organization — `routes/promotions.py:33-37`
- §3.7 — insert — ambiguity — activation sets `status`/`version` only; benefit figures untouched, no disclosure re-resolution — `routes/promotions.py:142-143`
- §3.7 — revise — mismatch — negative `actual_units`/`remitted_cents` is tested for presence/type at rung 3 but for negativity at rung 35 (behind ownership/state/window), not as a request-shape failure; segregation scan covers registrations of any status — `routes/promotions.py:151-183`
- §3.7 — insert — ambiguity — promotion listing `state_code` filter matches any element of `state_codes` — `routes/promotions.py:207-209`
- §3.8 — insert — ambiguity — `included_clauses` optional, defaults empty, may be empty, verbatim ordering/duplicates, non-canonical member → `ERR_INVALID_REQUEST`; no uniqueness rule on (org, state, material_type) — `routes/promotions.py:227-228`
- §3.8 — insert — ambiguity — the three re-resolution triggers are exhaustive: settling or halting a promotion changes the live set but re-resolves nothing, so stored `compliance_status` goes stale — `routes/promotions.py:195` vs `services/derive.py:118-130`
- §3.9 — insert — ambiguity — sweep's optional `state_code` narrows both passes; not shape-checked, so blank → `ERR_INVALID_REQUEST`, unknown → `ERR_STATE_PROFILE_NOT_FOUND` — `routes/enforcement.py:150-152`
- §3.9 — insert — ambiguity — on direct issuance the filing need not belong to the named organization; action booked against the supplied `organization_id` while `state_code`/penalty/cure deadline come from the filing — `routes/enforcement.py:32-41`
- §3.9 — insert — ambiguity — `penalty_cents_override` may not be negative — `routes/enforcement.py:30`
- §3.9 — insert — ambiguity — issuing `CEASE_SOLICITATION_ORDER` directly does not cease the filing or move `ceased_state_codes`/`solicitation_posture` — `routes/enforcement.py:41-43`
- §3.9 — insert — ambiguity — `remediation_note` required, must be a string, may be empty or blank — `routes/enforcement.py:52-53`
- §3.9 — revise — ambiguity — widened "leaves `penalty_outstanding_cents` alone" to the whole organization row (`updated_at`, `Organization.version`); `settlement_total_cents` recomputed and overwritten on each pass — `routes/enforcement.py:67-72`
- §3.9 — insert — ambiguity — a cure against a zero settlement reports `ERR_INVALID_ENFORCEMENT_STATE` — `routes/enforcement.py:90-94`
- §3.9 — insert — ambiguity — on ESCALATE a filing outside `DELINQUENT`/`CEASED` reports `ERR_INVALID_REGISTRATION_STATE`, after the enforcement-status gate but before the cure-window gate — `routes/enforcement.py:100-104`
- §3.9 — revise — ambiguity — whitespace-only `vacate_reason` also rejected; the reason is validated but never persisted — `routes/enforcement.py:115`

### Pass 3 (services + core modules) — 9 changes
- §2.1 — revise — ambiguity — a whitespace-only header value is `ERR_UNAUTHENTICATED`, not just an empty one — `auth.py:33`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alphanumeric characters — `response.py:10,18-19`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from the host's real clock, so it moves between two requests at the same logical instant — `response.py:22-27`
- §2.3 — insert — ambiguity — identical `created_at` values (the norm under a frozen clock) are tie-broken by insertion sequence, so `created_at` ascending is creation order everywhere §3 processes records in that order — `db.py:44-46,91-97`
- §2.6 — insert — ambiguity — integer-declared fields reject a boolean, a numeric string and a number with a decimal point (`2500.0`); the two fraction fields accept whole or fractional numbers but still reject a boolean — `validate.py:81-84,104-114`
- §2.11 rung 3 — insert — ambiguity — an absent/empty body reads as `{}` (a wholly-optional payload accepts a bodiless request), a non-object body is `ERR_INVALID_REQUEST`, and instants parse permissively (`Z`, explicit offset normalised to UTC, space separator, bare date, zoneless read as UTC) — `validate.py:32-47`, `dates.py:27-46`
- §2.11 rung 6 — revise — ambiguity — `ERR_OFFICER_NOT_FOUND` (404) is resolved at the ownership rung, so it outranks the status/posture/segregation gates — `auth.py:66-68`, `routes/registrations.py:193`
- §3.9 — revise — **mismatch** — disclosure re-resolution after a voided contract covers every state in that contract's own `state_codes`, not only the lapsed state; the prior "for those states" read the other way — `cascades.py:274`
- §3.9 — insert — ambiguity — escalating an action whose filing is already `CEASED` fires none of the three links and leaves the organization row untouched (`Organization.version` and `updated_at` included) while the action still moves to `ESCALATED` — `cascades.py:204-213`, `routes/enforcement.py:96-105`
- §5 — insert — ambiguity — an undeclared path and an unsupported method report `ERR_INVALID_REQUEST` with the routing layer's own 404/405 rather than 422 — `app.py:38-44`

**Cross-pass consistency:** pass 3 re-verified the pass-1/2 sentences its slice touches (§2.5 `touch_once` semantics and the sweep's per-candidate organization increment, §3.2's restating-write org bump, §3.4's single whole-row recomputation, §3.5's untouched-filing-row clause) against `db.py`, `cascades.py`, `derive.py` and the `apply_restatement` call site — all agree. The only correction needed was the §3.9 "for those states" phrase, which came from the original PRD wording rather than an earlier pass's insert.

**Orchestrator independent verification:** PRD_COMPLETED.md is 441 lines / 121,756 chars, is NOT byte-identical to PRD_FINALIZED.md (`cmp` differs; 84 changed lines in the diff), retains all 5 `## ` section headings, and ends on the complete final table row `ERR_DUPLICATE_IDENTIFIER | 409 Conflict`. No implementation file was modified in Steps 8 or 9, so the Step 7 sweep evidence (8/8 rounds at 120/120) remains valid for the delivered implementation.

## Pipeline complete — 2026-09-04T00:05:00.000Z

All nine steps finished. Deliverables in place: SCAFFOLD.yaml + the two design indices, `test_helpers/` (2,022 lines) and `test_suite/` (120 tests), `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (3,284 lines, 49 endpoints), and `results.1..8.json` all green at 120/120.
