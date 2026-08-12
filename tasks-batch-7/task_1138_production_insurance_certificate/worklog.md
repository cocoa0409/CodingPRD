# Worklog — task_1138_production_insurance_certificate

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_1138_production_insurance_certificate` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T00:20:00.000Z

Subagent generated all three scaffold artifacts (difficulty parameter "harder than expert level" applied): SCAFFOLD.yaml (12 entities — Production, Policy, CastMember, CastEndorsement, Certificate, Claim, ClaimEvent, ClearanceItem, CompletionBond, ForeignTravelExtension, PayrollAudit, RenewalOffer; coverage_posture posture-driven gating, optimistic concurrency, dual-variant payroll premium calculation, cascading side effects), SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 instances), SCAFFOLD_CORNER_DESIGN.yaml (25 instances). The subagent's turn ended while fixing lint check (f) FK_REVERSE_UNREACHABLE (13 violations: lint could not derive collection segments with api_prefix=/productions); the orchestrator applied the subagent's own diagnosed fix directly — api_prefix set to "" and 10 flat read-alias endpoints added (GET+list for /cast-endorsements, /claims, /claim-events, /payroll-audits, /renewal-offers). scaffold_lint.py now reports: clean lint — 72 endpoints, 12 entities, 18 §1.8 + 25 §1.9 instances, 367 calls scanned, 0 violations.

## Step 3: Copy shared files — 2026-08-11T00:21:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1138_production_insurance_certificate/workspace/INSTRUCTION.md (bash-only step).

## Step 4: Generate PRD — 2026-08-11T00:40:00.000Z

Task complete. The PRD is fully written and verified at `workspace/PRD.md` (353 lines). Key numbers:

- §2: 10 subsections (2.2 emitted byte-verbatim from the skill's canonical source, script-verified)
- §3: 10 workflow subsections, 573 backticked tokens, zero path/method violations
- §4: 72 endpoint rows (4 columns only); §5: 37 error rows (2 columns), diff-verified against the catalog
- Contract 1: 95/95 required identifiers present; Contract 2: all 20 validation priorities, 3 OCC rules, 57 transitions, 9 calculations, and every cross-entity side effect expressed in prose; Contract 3: PASS
- One fidelity note: scaffold state machines nominate `ERR_PRODUCTION_NOT_ACTIVE` and `ERR_CERT_WINDOW_ELAPSED`, which are absent from the error catalog; both were preserved in §3.5 prose (the latter flagged as the alias of `ERR_WINDOW_ELAPSED`) while §5 lists only the 37 catalog entries.

## Step 5: Generate unit tests — 2026-08-11T01:05:00.000Z

All files written, compiled, and audited. Summary:

## Coverage

- **Queue A (Difficulty):** 18/18 instances covered, **36 tests** (exactly 2 per instance, each tagged `Design: Difficulty/<rule_id>/<instance.name>`)
- **Queue B (Corner):** 25/25 non-stub instances covered, **25 tests** (1 per instance, tagged `Design: Corner/<section>/<instance.name>`); the corner index contains 0 `excluded_because:` stubs
- **Total: 61 tests** across 9 files. Automated audit confirmed: every tag resolves verbatim to a `name:` in the source yaml, every instance meets its count, zero unknown/duplicate/untagged tests, zero `skip`/`skipif`/`xfail` markers, and all 92 long PRD citations survive whitespace-normalized literal grep of PRD.md.
- `python -m py_compile` passes on all 19 files; all modules import cleanly.

## Skipped instances

None. All 43 instances passed the PRD-first two-condition filter.

Two judgment calls (documented in the tests' docstrings, not skipped):
1. `endorsement_issue_requires_policy_bound` — PRD §3.2 mandates rejection when the policy is QUOTED but names no unique error (two readers could pick `ERR_INVALID_STATE` or `ERR_REFERENCED_STATE_INVALID`). The rejection test uses `validate_error_is_one_of([...])` per the error-precedence escape hatch; the second test is the fully-derivable positive control (issue succeeds when BOUND).
2. `premium_provisional_vs_final_after_audit` — the yaml's asserted literal `provisional == 4550000` contradicts its own derivation comment (`... = 3630000`) and the PRD §3.1 formula. I asserted the PRD-uniquely-derived values (provisional 3630000, final 4356000, delta ±726000).

## Setup adjustments baked into fixtures (recipe gaps fixed, intent preserved)

- `setup_cast_policy_active_for_audit` advances the logical clock past the policy `effective_date` before posting the audit — PRD §3.10 only allows posting against `ACTIVE`/`EXPIRED` policies, and the recipe never triggered the BOUND→ACTIVE tick.
- OCC staleness in `occ_stale_version_on_certificate_issue` is produced by binding a second policy (PRD §3.1 explicitly increments production `version` on bind) rather than by creating a certificate, whose version side-effect the PRD does not state.
- The bond-issuance flow assumes the only non-deadlock reading of §3.4/§3.7 (a required-but-not-yet-ISSUED bond cannot self-block its own issuance; otherwise the endpoint is unreachable and `ERR_BOND_NOT_ISSUED` at activation unsatisfiable).

## File list

`test_helpers/`: `__init__.py`, `types.py` (15 status enums + 12 entity TypedDicts; ClaimEvent correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (60 endpoint methods), `api_errors.py` (37 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (counter-uniquified `production_code`/`policy_number` to respect §2.10 uniqueness), `constants.py`, `test_users.py` (8 opaque roles), `fixtures.py` (clock helper, bind/activate/issue OCC-fresh helpers, claim/cast/bond/travel/audit composite setups).

`test_suite/`: `conftest.py`, `test_01_production_registration.py` (6), `test_02_security_rbac.py` (3), `test_03_posture_gating.py` (7), `test_04_premium_calculations.py` (6), `test_05_cast_endorsement_workflows.py` (4), `test_06_certificate_workflows.py` (11), `test_07_claim_workflows.py` (12), `test_08_production_lifecycle.py` (8), `test_09_foreign_travel.py` (4).

## Step 6: Generate implementation — 2026-08-11T01:05:00.000Z

Done. Summary of the generated implementation:

## File list
All under `workspace/implementation/`:

- `start.sh` — executable; guarded `pip install` (no-op once Flask present); `exec python3 app.py` in foreground
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry; binds `0.0.0.0:$PORT` (default 10000); envelope-shaped 404/405/exception handlers
- `db.py` — in-memory store (dicts, RLock, logical clock booting at exactly 2026-05-01T00:00:00Z, cert issuance sequences); no seeding anywhere
- `errors.py` — `ApiError` + full error catalog (incl. `ERR_PRODUCTION_NOT_ACTIVE`→422, named in PRD §3.5/state machine but absent from the catalog)
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`
- `middleware.py` — X-User-Role/X-User-ID auth (401), per-endpoint RBAC (403)
- `util.py` — ISO8601 parse/format (3 fractional digits), field validators, pagination (limit default 10 clamp [1,100], offset 0), serialization, nested-parent 404 resolution
- `services/posture.py` — 8-step posture derivation with lexicographically sorted reasons; per-request single version bump
- `services/pricing.py` — per-step round-half-up tiered premium (CAST stunt/essential loadings, FOREIGN_TRAVEL traveler loading, 25000 floor), per-tier-rounded bond premium, loss ratio, renewal quote
- `services/claims.py` — deductible calc (min of per-claim/loss/remaining cap; cap = aggregate/4) + cap-exceeded trigger
- `services/lifecycle.py` — idempotent fixpoint sweep firing all 8 time-based auto-transitions on clock-set and after enabling mutations
- `routes/` — 11 modules: clock, productions, policies, cast (members+endorsements), certificates, claims (+events), clearances, bond, travel, audits (payroll+renewal), flat aliases

## Endpoint count
**72** routes registered — verified programmatically against the live app; matches SCAFFOLD.yaml §1.5 exactly, including the five flat read-alias pairs (`/cast-endorsements`, `/claims`, `/claim-events`, `/payroll-audits`, `/renewal-offers` + `/{id}`) and `POST /_clock/set_current_utc`. (Orchestrator route-parity check confirms: declared 72 == registered 72, only extra is Flask's built-in /static/ route.)

## Boot-test result (PORT=18231)
- `python -m py_compile` on all 21 .py files: clean.
- No headers → 401 `ERR_UNAUTHENTICATED`; wrong role → 403 `ERR_FORBIDDEN` — correct envelopes.
- `POST /productions` → 201, DRAFT/UNBOUND, version 1.
- Policy create → 201 QUOTED; bind with `expected_production_version:99` → 412 `ERR_STALE_VERSION`; with correct version → 200 BOUND with premium 2,400,000 (200M × 1.20% × 1.00, verified by hand).
- Clock set to 2026-05-20 → echoes input verbatim, sweep fired → policy auto-transitioned BOUND→ACTIVE (version bumped to 3).
- Fresh restart → `total_count: 0`, clock back at 2026-05-01: confirmed empty-state boot per `per-test-server` isolation. Server killed cleanly by PID (other tasks' servers on this host left untouched).

Key spec-fidelity decisions: OCC checks ordered state→OCC→posture per the §2.9 pipeline; renewal accept checks offer expiry before state so `ERR_RENEWAL_OFFER_EXPIRED` (422) survives the sweep's auto-expiry; certificate windows enforce half-open policy containment (`location_end < expiry_date`) but end-inclusive outer envelope (pp_end + 30d); deductible cap rejects when `min(deductible, loss) > remaining_room`; claim adjust toggles UNDER_REVIEW↔ADJUSTED; segregation-of-duties compares settler X-User-ID against the internally recorded claim submitter.

## Step 7: 8-round stability sweeps — 2026-08-11

### Iteration 1 (baseline): 57/62 in all 8 rounds
Union of failures (all consistent, none flaky):
- `test_04::test_bond_premium_per_tier_rounding`, `test_04::test_bond_premium_tier_one_boundary`,
  `test_06::test_issue_voided_cert_on_restricted_posture_returns_invalid_state` — `NameError: name 'api' is not defined`:
  module-scope helpers referenced the `api` fixture name. TEST BUG (mechanical): switched helpers to `api_client`.
- `test_08::test_bond_claim_cascade_depth2`, `test_08::test_bond_claim_posture_reasons_bond_not_issued` —
  setup failed at `issue_bond` with 422 `ERR_POSTURE_BLOCKS_BOND` (posture RESTRICTED from the bond's own
  BOND_NOT_ISSUED). IMPLEMENTATION BUG: literal reading of PRD §3.4+§3.7 deadlocks bond issuance, making
  the ISSUED state (and the whole claim/release cascade the tests assert from §3.7 verbatim) unreachable.
  Fixed `issue_bond` to evaluate the posture gate via `derive_posture(prod, assume_bond_issued=True)` so the
  bond cannot self-block; other restrictions (open injury, uncleared mandatory clearance, UNBOUND) still gate.

### Iteration 2: 60/62 in all 8 rounds
- Same two bond-claim tests failing, now with `NameError: name 'api'` at `_setup_bond_claim_scenario`
  (test_08 line 149) — same mechanical test bug, previously masked by the issue_bond 422. Fixed
  (`api.acknowledge_claim` → `api_client.acknowledge_claim`) after iteration 2 had already launched.
- Bond posture fix confirmed working: setup progressed past `issue_bond` in every round.

### Iteration 3: 62/62 in ALL 8 rounds — CLEAN SWEEP
No deletions were needed at any point: every failing assertion traced to a verbatim PRD rule
(§2.8/§2.9/§3.5/§3.7), and the fixes were two mechanical test bugs plus one implementation
deadlock fix. No test was weakened; no implementation check required by the PRD was removed.

## Step 7: Run tests and iterate — 2026-08-11T01:15:00.000Z

Clean 8-round parallel sweep achieved: **62/62 passed in every round**. Final summary:

**Iterations run:** 3 (baseline 57/62 → 60/62 → 62/62 × 8 rounds, all passing)

**Tests deleted:** None. Every failing assertion traced to a verbatim PRD rule (§2.8, §2.9, §3.5, §3.7); no PRD-silence or unique-derivability collapses were found.

**Fixes applied to `test_suite/`** (the bugs lived in module-scope helpers inside test modules, not in `test_helpers/`):
- `test_suite/test_04_premium_calculations.py` — `_underwritten_bond()`: `api.` → `api_client.` (3 calls). The `api` pytest fixture only exists as a test-function parameter; module-scope helpers must use the imported client. Was causing `NameError` in `test_bond_premium_per_tier_rounding` and `test_bond_premium_tier_one_boundary`.
- `test_suite/test_06_certificate_workflows.py` — `_setup_restricted_with_voided_cert()`: same `api.` → `api_client.` fix (2 calls), fixing `test_issue_voided_cert_on_restricted_posture_returns_invalid_state`.
- `test_suite/test_08_production_lifecycle.py` — `_setup_bond_claim_scenario()`: same `api.` → `api_client.` fix (1 call), fixing `test_bond_claim_cascade_depth2` and `test_bond_claim_posture_reasons_bond_not_issued` (this instance was masked in iteration 1 by the implementation bug below).

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/posture.py` — `derive_posture()` gained an `assume_bond_issued=False` parameter that discounts the bond's own not-yet-issued contribution in the §3.4 ladder.
- `workspace/implementation/routes/bond.py` — `issue_bond()` now evaluates the §3.7 posture gate via `derive_posture(prod, assume_bond_issued=True)` instead of reading the stored `coverage_posture` directly. Rationale: a literal reading of §3.4 ("a required completion bond that is not yet `ISSUED`" → RESTRICTED) plus §3.7 (issuance requires BOUND_PARTIAL/BOUND_FULL) deadlocks — ISSUED would be unreachable and §3.4's `ERR_BOND_NOT_ISSUED` activation gate unsatisfiable. The bond cannot self-block its own issuance; all other restrictions (open injury claims, uncleared mandatory clearances, UNBOUND) still gate, keeping `ERR_POSTURE_BLOCKS_BOND` reachable. No PRD-required check was removed.

**Stability note:** zero flakiness observed — every failure repeated identically in all 8 rounds of its iteration, and the final sweep is uniformly green.

Orchestrator verification: all 8 `results.{1..8}.json` files present on disk, each `passed: 62, total: 62, failed: 0`.

## Step 8: Finalize PRD — 2026-08-11T01:25:00.000Z

The diff is exactly one paragraph revision in §3.7 — minimal and scoped. The three test-suite `api.` → `api_client.` fixes were pure fixture bugs (NameError in module-scope helpers) with no PRD signal, so they produced zero PRD edits, as expected.

One final consistency check on the new wording against the enumerated paths: the sentence claims UNBOUND blocks bond issuance — verified against the ladder (`not bound_lines` → UNBOUND, which is not in `("BOUND_PARTIAL","BOUND_FULL")`, so `bond.py:114` refuses it). CANCELLED → SUSPENDED → refused. Open injury / uncleared mandatory clearance → RESTRICTED → refused regardless of the flag (flag only discounts the bond rung). Missing-lines-but-something-bound → BOUND_PARTIAL → *permitted*; wording says "missing required lines (a fully UNBOUND production)" blocks — correctly scoping the block to UNBOUND, since partial coverage yields BOUND_PARTIAL which the impl permits. All consistent.

## Summary

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 353 lines → PRD_FINALIZED.md 353 lines (0.0% delta; single in-place paragraph revision, one paragraph grew by three sentences on the same line).

**Changes (1 total):**
- **§3.7 Completion Bonds** — revise — extended the bond-issuance posture-gate sentence to pin the impl's resolution of the §3.4/§3.7 deadlock: for the bond-issuance gate alone, the posture ladder is evaluated with the bond's own not-yet-issued contribution discounted (a required bond cannot self-block its own issuance); all other restrictions (open injury claims, uncleared mandatory clearances, UNBOUND, CANCELLED) still gate with `ERR_POSTURE_BLOCKS_BOND`; the stored `coverage_posture` is unaffected, so certificate issuance and foreign travel approval still see the literal §3.4 posture — `workspace/implementation/routes/bond.py:110-116`, `workspace/implementation/services/posture.py:18-27,74-77`.

**No edits from test-suite fixes:** the three `api.` → `api_client.` fixes in `test_04_premium_calculations.py`, `test_06_certificate_workflows.py`, `test_08_production_lifecycle.py` were pure fixture NameErrors with no PRD signal — zero PRD edits.

**Per-edit pre-edit search log (the single edit):**
- **(a) Subject:** whether a required-but-not-yet-ISSUED bond's own `BOND_NOT_ISSUED` contribution counts against the posture gate when issuing that bond (§3.4 ladder vs §3.7 gate).
- **(b) Impl paths enumerated and read/grepped:** `services/posture.py` in full (`derive_posture` flag semantics; `recompute_posture` at line 129 always default-flag); all 30+ `recompute_posture`/`recompute_all_postures` callsites across `routes/{productions,claims,policies,cast,clearances,bond,audits}.py` and `services/lifecycle.py:114` (all default-flag → stored posture literal per §3.4); all three posture-gated endpoints — `routes/certificates.py:144-147` (stored posture), `routes/travel.py:101-104` (stored posture), `routes/bond.py:113-116` (discounted re-derivation); activation bond gate `routes/productions.py:106-111` (direct bond-status read, posture-independent); `errors.py:34-36` (status codes).
- **(c) Wording adjustment:** scoped the discount explicitly to "this gate alone," added that the stored `coverage_posture` is unaffected (so cert/foreign gates against a not-yet-issued bond still refuse — matching `certificates.py`/`travel.py` stored-posture reads), and enumerated the still-blocking restrictions including UNBOUND (verified against the ladder's `not bound_lines` branch). §3.4 and §2.7 left verbatim: §3.4 accurately describes the stored derivation used by every `recompute_posture` callsite, and narrowing either would have created new mismatches at the cert/foreign/activation sites.

## Step 9: Complete PRD — 2026-08-11T01:50:00.000Z

Done. `workspace/PRD_COMPLETED.md` written and verified.

**Size**: PRD_FINALIZED.md 353 lines / 60,937 chars → PRD_COMPLETED.md 356 lines / 70,480 chars (char-delta +9,543; diff touches 22 paragraphs/rows, all inline — no new sections).

**Counts**: 26 ambiguity-pins, 8 mismatch-revisions (several edits carry one of each; counted by distinct behavior).

**Mismatch-revisions** (PRD said X, impl does Y):
- §2.9 step 16 — revise — mismatch — renewal-offer expiry was grouped under `ERR_WINDOW_ELAPSED`; impl rejects acceptance with `ERR_RENEWAL_OFFER_EXPIRED` — implementation/routes/audits.py:232-233
- §2.9 step 17 — revise — mismatch — settlement-overage was classified as `ERR_FISCAL_CONSTRAINT_VIOLATED`; impl uses `ERR_SETTLEMENT_EXCEEDS_RESERVE` — implementation/routes/claims.py:217-219
- §3.2 + §4 row — revise — mismatch — flat cross-production endorsement list does not filter by `endorsement_type` (only `cast_member_id`, `policy_id`, `status`); per-production list keeps all four — implementation/routes/flat.py:17-31 vs routes/cast.py:207-230
- §3.2 — revise — mismatch — "a FAILED outcome carries no precondition" softened: impl accepts outcomes only from `PENDING` (plus `CONDITIONAL`→`CLEARED`); FAILED carries no *production-state* precondition but still requires `PENDING` — implementation/routes/cast.py:120-129
- §3.5 — revise — mismatch — deleted the `ERR_CERT_WINDOW_ELAPSED` alias parenthetical; impl emits only `ERR_WINDOW_ELAPSED` — implementation/routes/certificates.py:183-185, errors.py (no such constant)
- §3.5 — revise — mismatch — cert auto-expiry on "production or policy … cancelled" corrected: cancellation voids (DRAFT/ISSUED → VOIDED); only policy expiry flips ISSUED → EXPIRED — implementation/routes/productions.py:219-222, policies.py:218-224, services/lifecycle.py:14-21
- §3.10 — revise — mismatch — audit window/payroll validation occurs at creation, not submission; submit/resubmit are bare status transitions carrying no corrected figures — implementation/routes/audits.py:51-79, 104-117
- §5 — insert — mismatch — catalogue claimed to list every error identifier but omitted `ERR_PRODUCTION_NOT_ACTIVE` (422); row added — implementation/errors.py:60

**Ambiguity-pins** (PRD silent, pinned to impl):
- §2.2 — insert — unknown path/method → `ERR_NOT_FOUND` 404; missing/unparseable JSON body treated as `{}`; non-object body → `ERR_INVALID_REQUEST` — app.py:26-37, util.py:69-76
- §2.3 — insert — limit/offset clamped (not rejected); non-integer → 400; `created_at` ties break by creation order; `has_more` = offset+limit < total — util.py:164-203
- §2.4 — insert — request datetimes accept `Z`/numeric offset, naive read as UTC, returned normalized with 3 fractional digits; omitted optionals and not-yet-computed fields read back `null` — util.py:15-38
- §2.5 — insert — clock response echoes the supplied `to_iso8601` verbatim; any well-formed timestamp accepted (even backwards); missing field → 400 — routes/clock.py:15-23
- §2.6 — insert — 25000-cent floor applies to provisional/final policy premiums only, not bond premium or renewal offered premium — services/pricing.py:92-94,103-114,134-144
- §2.7 — insert — a posture recomputation that changes neither field does not increment production `version` — services/posture.py:127-133
- §2.8 — insert — omitted/non-integer OCC version field → `ERR_INVALID_REQUEST` 400 — routes/policies.py:58-66, certificates.py:130-133, audits.py:240-243
- §2.9 outro — insert — two endpoint-local orderings: cert-issuance gate order per §3.5 (`ERR_PRODUCTION_NOT_ACTIVE` after OCC, before posture); renewal-accept checks expiry first — routes/certificates.py:125-185, audits.py:230-260
- §2.10 — insert — `CERT-<prod>-<seq>`: `<prod>` = `production_code`, `<seq>` = per-production 1-based issuance counter — routes/certificates.py:187-188
- §3.1 — insert — `budget_cents` ≤ 0 → `ERR_FISCAL_CONSTRAINT_VIOLATED`; new production's `posture_reasons` = [] until first mutation — routes/productions.py:45-58
- §3.1 — insert — policy numeric bounds violations → `ERR_FISCAL_CONSTRAINT_VIOLATED`; policy creation not gated on production status — routes/policies.py:88-97
- §3.1 — insert — bind against non-DRAFT/ACTIVE production → `ERR_REFERENCED_STATE_INVALID`, after OCC, before line prerequisites — routes/policies.py:155-157
- §3.1 — insert — FOREIGN_TRAVEL loading sums `travelers_count` over all extension records regardless of status — services/pricing.py:80-90
- §3.2 — insert — `weekly_salary_cents` error name; registration not gated on production status; `endorsement_required` derived at registration; exam-expiry sweep also nulls `physical_exam_expires_at`; retake from non-FAILED → `ERR_INVALID_STATE` — routes/cast.py:69-81, lifecycle.py:68-82, cast.py:152-155
- §3.2 — insert — drafting against non-CAST policy → `ERR_REFERENCED_STATE_INVALID`; drafting not gated on policy status; issue-time policy-state failure is `ERR_REFERENCED_STATE_INVALID` checked after the type-match gate — routes/cast.py:181-183,198-202,266-270
- §3.3 — insert — registration not gated; empty `waiver_justification` → `ERR_INVALID_REQUEST` 400 and not persisted; bad outcome → `ERR_INVALID_ENUM`, but terminal items fail state-first — routes/clearances.py:104-121
- §3.5 — insert — draft-time validation scope (fields + window ordering only; containment deferred to issuance); empty `coverage_lines` allowed; drafts carry `certificate_number` null; issuance gate order pinned; elapsed means strictly past `location_end`; void after window open → `ERR_INVALID_STATE` — routes/certificates.py:57-93,125-212
- §3.6 — insert — `territory_code` validated only as non-empty string; fiscal error names; filing not gated; approval gate order (posture → FT policy exists (`ERR_REFERENCED_STATE_INVALID`) → half-open policy overlap → extension overlap → envelope); denial at/after window start → `ERR_INVALID_STATE` — routes/travel.py:40-53,91-162
- §3.7 — insert — apply-time rules: positive amount, second application → `ERR_DUPLICATE_IDENTIFIER` 409, `requires_completion_bond` not checked; bond claim with no qualifying claim → `ERR_INVALID_STATE` 409; claim cascade scope (policies in QUOTED/BOUND/ENDORSED_PENDING/ACTIVE, certs in DRAFT/ISSUED; endorsements/travel untouched) — routes/bond.py:43-50,132-152
- §3.8 — insert — occurrence window inclusive at both ends (reporting, cap accumulation, loss ratio alike); aggregate cap = `aggregate_limit_cents // 4` integer division; cap check compares min(deductible, loss) > remaining room; claim born with `reserve_cents` = carrier payable; negative `new_reserve_cents`/`settlement_amount_cents` → `ERR_FISCAL_CONSTRAINT_VIOLATED`; missing denial reason → `ERR_INVALID_REQUEST`; SoD fires before amount is read; event payload contents per type — routes/claims.py:71-96,144-239, services/claims.py:8-42
- §3.9 — insert — wrap-scheduled audit copies policy window, `auditor_name` null, `reported_payroll_cents` 0; policy cancel voids only DRAFT/ISSUED certs; production cancel lapses bond only from APPLIED/UNDERWRITTEN/ISSUED; policy expiry takes only ISSUED certs — routes/productions.py:177-188,229-234, policies.py:218-224, lifecycle.py:14-21
- §3.10 — insert — audit creation not gated on policy status; post against non-ACTIVE/EXPIRED policy → `ERR_REFERENCED_STATE_INVALID`; post returns the audit; bad `renewal_term_months` → `ERR_INVALID_ENUM`; offer creation not gated; accept check order (expiry → status → OCC → policy status → pending audits); month extension is calendar-months with day clamping; accept returns the offer — routes/audits.py:120-142,164-273, util.py:50-62

The scan covered all 11 route modules, all 4 services, and the 6 foundation files; PRD_COMPLETED.md now pins every observable behavior found there.
