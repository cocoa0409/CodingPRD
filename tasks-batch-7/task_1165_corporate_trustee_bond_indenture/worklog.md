# Worklog — task_1165_corporate_trustee_bond_indenture

## Step 1: Create task directory — 2026-08-11T00:00:00.000Z

Pre-assigned output folder `tasks/task_1165_corporate_trustee_bond_indenture` with `workspace/` subdirectory already existed; Step 1 treated as done per orchestrator instruction (no auto-index scan run).

## Step 2: Generate scaffold — 2026-08-11T07:42:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/` and lint-clean.

## Verdict block (verbatim from `scaffold_lint.py`)

```
Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     16
  §1.8 instances scanned:     28
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  782

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — 101,965 bytes (§1.0–§1.7 only; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 110,051 bytes (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 118,297 bytes (single top key `scaffold_corner_design`)

## Counts

| Metric | Count |
|---|---|
| Entities (§1.1) | 16 |
| Endpoints (§1.5) | 72 |
| State machines (§1.2) | 14 (+3 OCC concurrency rules, §1.2.1) |
| Calculations (§1.3) | 8 |
| Validations (§1.4) | 26 (priority-ordered) |
| Error codes (§1.6) | 29 (all triggerable) |
| Roles (§1.7) | 5 (all with `identity:`) |
| Difficulty instances (§1.8) | 28 (9 rule blocks; rules 1–5, 7–9 ×3, rule 6 ×4) |
| Corner instances (§1.9) | 56 total: 48 active + 8 `excluded_because` stubs |

## Harder-than-expert design choices

- **Archetype**: compliance/audit + multi-party negotiation; flat topology, cyclic state-machine shape, segregation-of-duties role model (declare/confirm, verify/decide, draft/issue enforced by `X-User-ID` mismatch).
- **Rule 1**: three dual-variant calcs on distinct domains — day-count conventions (ACT_360 gross 25,416,667 vs ACT_365 25,068,493 for identical inputs), consent tabulation (RECORD_DATE passes / CURRENT_OUTSTANDING fails on identical ballots across a mid-window redemption), covenant TTM vs quarterly-annualized basis.
- **Rule 2**: all three modes — tiered+state-switched+capped extraordinary fees (893,750 / 618,750 / capped 10,000,000), floor-then-largest-remainder pro-rata with `created_at` tie-break (never `id`), and a circular-looking collateral-coverage calc with pinned evaluation order (substitute haircut tier selected *before* the substitute is included → 12,542 bps).
- **Rule 3**: parallel funding×distribution dimensions on PaymentRun, ISSUED→DISPUTED→AMENDED→ISSUED fee cycle, CIRCULATING⇄EFFECTIVE direction oscillation.
- **Rule 4**: depth-4 default-confirm suspension cascade (confirm→Indenture→runs→records→holder totals), depth-3 covenant-cure and consent-waiver cascades from different triggers.
- **Rule 6**: inclusive 25% quorum vs strict >50% rescission boundary, exact 12,500-bps coverage floor, zero-ballot close, zero-cent distribution records, off-by-one eligible-principal edge (900,000,000 < 900,000,001).
- **Rule 8**: three genuinely different interval semantics — half-open payment windows (adjacency allowed), closed solicitation windows (shared date collides), minimum-buffer notice period (equality allowed).
- All 28+48 test recipes replay cleanly against §1.2/§1.4/§1.6; every numeric assert is a literal pre-computed by executing the formulas in Python. Enum closure was audited (DEFEASED/TERMINATED/COMPLIANT/CLOSED removed as unreachable), and no forbidden concurrency vocabulary appears anywhere.

## Step 3: Copy shared files — 2026-08-11T07:43:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1165_corporate_trustee_bond_indenture/workspace/INSTRUCTION.md` (bash-only step).

## Step 4: Generate PRD — 2026-08-11T07:54:00.000Z

The PRD is complete and verified on disk. Summary:

## Output
- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/workspace/PRD.md`
- **Size**: 57,754 bytes, 347 lines
- **Sections**: 1. Introduction; 2. Global Specifications (2.1 RBAC, 2.2 API Response Structure [verbatim], 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Time-Driven Sweep, 2.6 Monetary Precision/Rounding/Basis-Point Arithmetic, 2.7 Optimistic Concurrency Control, 2.8 Validation Discipline & Evaluation Order, 2.9 Nested Resource Retrieval, 2.10 Hierarchical Consistency & Cascade Reconciliation); 3. Business Logic & Workflows (3.1 Indenture setup/activation, 3.2 Holders & Positions, 3.3 Covenant Calendar & Certificates, 3.4 Payment Agency, 3.5 Defaults & Noteholder Direction, 3.6 Consent Solicitations, 3.7 Collateral Release/Substitution, 3.8 Fees & Extraordinary Services, 3.9 Successor Trustee Appointments); 4. Endpoint Definitions; 5. Error Code Catalogue
- **Endpoint coverage**: 72 of 72 scaffold endpoints in the §4 table (all paths verified present); 29 of 29 error IDs in §5

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 107 required, 107 present, 0 missing
- endpoints[].request_body/input + query/path identifiers: 82 required, 82 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed (full ordered stack in §2.8; per-endpoint orderings stated, e.g. collateral decide = SoD → default lock → coverage floor; ERR_INVALID_REQUEST explicitly last), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_indenture_version / expected_collateral_item_version / expected_default_case_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 13 machines checked, all transitions expressed (incl. cyclic OPEN→OPEN roll-forward, PaymentRun dual dimensions, three-outcome solicitation close), 0 missing
- calculations[]: 8 checked, 8 expressed in precise prose (interest accrual, pro-rata largest-remainder, tiered extraordinary fee, pinned-order collateral coverage, consent tabulation, ratio check, quorum tally, principal conservation), 0 missing
- validations[] conditions: 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed; ownership applies_to set of 10 endpoints enumerated
- entities[].fields[] structured content: reconstructible (defaults notice_period_days=30, grace_period_days=10; null-until executed_at/paid_at; conditional-required threshold/substitute/metric fields)
- sibling-branch symmetry: PASSED/FAILED/EXPIRED, 3 day-count bases, 2 tabulation bases, 2 ratio bases, 3 funding transitions, 3 waiver-source states, rescind/supersede pairs — equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 615
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Zero-Silence Rule adjudications
1. **INTEREST run `gross_amount_cents` at creation** — scaffold `side_effects` says "0 until execute" while the endpoint `note` says "provisionally computed at creation AND recomputed at execute". Direct conflict; I followed the note (provisional computation at creation, authoritative recomputation at execution from the then-current ACTIVE position set) as the more specific statement.
2. **Direction creation on a case not in `CONFIRMED`/`ACCELERATED`** — the endpoint description states the admitted states without naming an error; I mapped rejection to `ERR_INVALID_STATE` via the priority-5 state-admissibility validation category.
3. **`threshold_rule` (computed string on NoteholderDirection)** — rendered as a human-readable restatement of the governing threshold test rather than a stored formula literal.
4. **Logical clock plumbing** — startup default `2026-05-01T00:00:00Z`, input `to_iso8601`, and response field `current_utc` are specified in §2.5; §2/§3 describe the capability without the path (path appears only in §4).

## Step 5: Generate unit tests — 2026-08-11T08:39:00.000Z

Generation complete. Summary:

## Files generated

**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/`):

| File | Bytes | Contents |
|---|---|---|
| `__init__.py` | 979 | Barrel export (framework generics + PRD-specific) |
| `types.py` | 10794 | 5 roles + 25 status/field enums + 16 entity TypedDicts |
| `api_client.py` | 11393 | `ApiClient(GenericApiClient)` — one method per PRD §4 endpoint (78 methods) |
| `api_errors.py` | 3184 | 29 `ApiErrorId` values + HTTP map, registered via `set_error_http_status_map` |
| `assertions.py` | 11078 | 16 per-entity assertions + `assert_iso8601_ms_utc` + `assert_principal_conservation` |
| `factories.py` | 7560 | 17 payload factories (input fields only) |
| `constants.py` | 1838 | Fee tiers/cap, haircuts, quorum rules, clock start, defaults |
| `test_users.py` | 2505 | `TEST_USERS` + per-instance `make_*_headers` builders (entity-backed Noteholder threading) |
| `fixtures.py` | 21327 | Composite setups: active indenture+tranche+positions, funded/executed runs, confirmed defaults, directions, solicitations, collateral scenarios, defaulted/cured-default indentures |

**test_suite/**: `conftest.py` + 12 test files (`test_01_registration_and_envelope.py` … `test_12_trustee_appointments_occ.py`).

## Test counts — final audit PASS

- **105 test functions total**
- **Queue A (Difficulty): 56 tests over 28/28 instances** (exactly ≥2 each, zero shortfalls)
- **Queue B (Corner): 49 tests over 48/48 non-stub instances** (zero shortfalls); the 8 `excluded_because:` stubs were not translated and all their `difficulty_instance` cross-references resolve.
- 0 untagged, 0 dual-tagged, 0 unresolvable `Design:` tags; every tag is the docstring's last line.
- **Verbatim-citation check:** all 154 quoted PRD spans (≥40 chars) survive literal whitespace-normalized grep of PRD.md.
- **`python -m py_compile`: OK on all 22 files**; `import test_helpers` + `test_suite.conftest` succeed; no `skip`/`skipif`/`xfail` markers anywhere.

## Skipped instances

None. Every non-stub instance in both indices passed the PRD-first filter.

## Judgment calls worth flagging

1. **Collateral-coverage arithmetic corrected to PRD.** Three design instances precomputed coverage figures (12542, 12445, and a 12500-equality built from 995000000/796000000) using a 0.5%/2.5% haircut reading. PRD §2.6 pins "one hundred basis points equal one percent", so the 500 bps SECURITIES haircut is 5%. I translated with PRD-derived values: substitution-of-470M case → `post_release_coverage_bps == 11125`; the inclusive-floor instance was re-figured (tranche/position 760000000, C1 SECURITIES 1000000000 → pledged 950000000) so 12500 is hit exactly and APPROVE succeeds; the default-lock-gating instance uses C1 1000000000 (coverage 13025 ≥ 12500) so the gate is purely DefaultCase state, as the instance intends. Error-priority assertions (ERR_DEFAULT_LOCK before ERR_COVERAGE_BELOW_MINIMUM) hold under both arithmetics.
2. **`double_execute_rejected_idempotency`** uses `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` — PRD §2.8 rule 5 names both ids and §3.4 calls DISTRIBUTED "the terminal combined state" while still allowing reversal, so the exact id is not uniquely derivable (error-precedence silence pattern). The unique assertion (exactly one DistributionRecord survives) is still hard-asserted.
3. **`indenture_creation_defaults_and_computed_initialization`** asserts the four PRD-named initial values (DRAFT/0/CURRENT/0) but not `version == 1` — PRD never states the initial version number, only that it increments on mutation.

## Step 6: Generate implementation — 2026-08-11T08:39:00.000Z

Implementation complete. Summary:

## Files (in `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/workspace/implementation/`)

| File | Bytes | Role |
|---|---|---|
| start.sh | 396 | Launcher: guarded `pip install` (no-op once flask present), `exec python3 app.py`, foreground |
| requirements.txt | 11 | flask>=2.2 |
| app.py | 1,896 | App factory, error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| store.py | 1,914 | In-memory dicts (16 entity kinds), logical clock starting at exactly `2026-05-01T00:00:00Z`, mutation helpers (touch = updated_at + version bump, incl. cascades) |
| errors.py | 2,057 | All 28 catalog error IDs with HTTP statuses, ApiError |
| envelope.py | 3,021 | `meta`/`response_type`/`data` envelope, `req_` ids, 3-fractional-digit timestamps, limit/offset/total_count/has_more pagination (10/1/100/0) |
| auth.py | 1,668 | X-User-Role validation (401), per-endpoint role check (403), Noteholder/Issuer ownership (403) |
| validate.py | 3,791 | Shape validators (rule 26, checked last), ISO date/datetime parsing, month-roll, exact round-half-up |
| calc.py | 6,773 | interest_accrual (ACT_360/ACT_365/THIRTY_360, per-position rhu), pro-rata largest-remainder (frac DESC, created_at ASC, original DESC), tiered extraordinary fee (10h / 1.5x / 4x cap, status-dependent rate), pinned collateral coverage (haircuts, HIGH/STANDARD substitute tier, floor division), quorum/consent cross-multiplication, record-date snapshots |
| domain.py | 12,497 | Derived-field recomputes, default/resume/acceleration/rescission cascades, roll-forward, satisfaction bubble-up, clock sweep (OPEN→LATE→BREACHED + auto DefaultCase with 30-day cure deadline, direction LAPSED, PENDING→PAID settlement skipped under DEFAULTED/ACCELERATED) |
| routes_core/.py | 10,908 | clock, indentures, tranches, accounts, positions |
| routes_covenants.py | 8,226 | obligations + certificates/review |
| routes_payments.py | 15,589 | payment runs (fund/execute/reverse) + distribution records |
| routes_defaults.py | 14,304 | default cases, directions (OCC), endorsements, execute |
| routes_consents.py | 12,094 | solicitations, open/ballots/close/revoke |
| routes_collateral.py | 12,147 | items + release requests (OCC, verify/decide/effect) |
| routes_fees.py | 7,299 | fee invoices (issue/pay/dispute/amend) |
| routes_trustee.py | 5,738 | trustee appointments (OCC, accept/effect/rescind) |

## Route diff vs SCAFFOLD.yaml §1.5
**72 registered vs 72 declared — MISSING: none, EXTRA: none** (exact match, verified programmatically against the YAML).

## py_compile
All 16 `.py` files compile clean (`PY_COMPILE_ALL_OK` / `FINAL_PY_COMPILE_OK`).

## Smoke tests (fresh `bash start.sh` per run, killed after)
- Boot: 404 `ERR_NOT_FOUND` envelope on unknown route; 401 `ERR_UNAUTHENTICATED` without role header; 200 empty array with pagination meta; 201 indenture create with correct defaults; fresh reboot shows empty store and clock at `2026-05-01T00:00:00.000Z`.
- 62 functional checks across all workflows passed (3 initial failures were my test script's arithmetic, plus 2 real bugs found and fixed: run status must flip to DISTRIBUTED/REVERSED *before* recomputing tranche outstanding, and a missing `opt_enum` import). Coverage included: interest day-count per-position rounding, pro-rata largest-remainder with zero-cent records, notice period, funding shortfall/equality, settlement sweep, return, reverse bit-identical restoration, full-redemption → REDEEMED → SATISFIED → reverse restores ACTIVE, default confirm SoD + suspension cascade, cure at exact deadline, direction OCC 412, 25% inclusive / 50% strict quorum, accelerate/rescind cascades, direction lapse, covenant LATE→BREACHED ladder with auto-case, certificate accept cure + roll-forward, TTM vs quarterly ratio inclusive boundary, collateral coverage pinned order, default lock before coverage floor, substitution auto-create, supersede semantics, closed-interval solicitation overlap (adjacency collides), amendment application, appointment effectiveness date + draft-invoice voiding.

No seeding, no persistence files, in-memory dicts only; per-test reboots start clean.

## Step 7: Run tests and iterate — 2026-08-11T08:51:00.000Z

All 8 rounds pass 105/105. Clean sweep achieved — exiting with the summary.

---

## Summary

**Iterations run:** 2 (first sweep: 4 deterministic failures × 8 rounds; second sweep: 105/105 in all 8 rounds).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None — the helper layer (`fixtures.py`, barrel `__init__.py`) already defined and exported both `register_account` and `create_open_solicitation` correctly.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/test_suite/test_07_defaults_and_directions.py` — added `register_account` to the `from test_helpers import (...)` block; `test_endorsement_without_position_rejected` (line 378) used it without importing it (NameError).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/test_suite/test_08_covenants.py` — added `create_open_solicitation` to the import block; `TestConsentWaiverCascade._setup_waiver_scenario` (used by both waive-consent tests) referenced it without importing it (NameError).

3. `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/test_suite/test_06_payment_run_lifecycle.py` — `test_suspended_underfunded_execute_reports_state_error`: relaxed `validate_error(resp, ERR_INVALID_STATE)` to `validate_error_is_one_of(resp, [ERR_INVALID_STATE, ERR_INDENTURE_NOT_ACTIVE])` (helper added to imports). Reason: ERROR-PRECEDENCE-SILENCE — the fixture makes the run simultaneously SUSPENDED and under a DEFAULTED indenture; PRD §2.8 rule 5 places both error ids in the same priority-5 state-admissibility level with no intra-level ordering, and §3.4 names both gates ("the indenture must be `ACTIVE` (otherwise `ERR_INDENTURE_NOT_ACTIVE`)"; "a run whose distribution status is `SUSPENDED` also refuses execution under the state rules"), so a faithful PRD-only implementer could check either gate first. The PRD-pinned core assertion — priority-5 state error beats priority-20 `ERR_FUNDING_SHORTFALL` — is preserved via the explicit `actual != "ERR_FUNDING_SHORTFALL"` check.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful on all four failures.

Orchestrator disk verification: all 8 results.{1..8}.json present, each passed=105 total=105 failed=0.

## Step 8: Finalize PRD — 2026-08-11T08:57:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/workspace/PRD_FINALIZED.md` with exactly one inline insertion.

## Summary

**Line counts / %-delta:** PRD.md = 347 lines; PRD_FINALIZED.md = 347 lines; 0.0% line delta (the change is a single sentence inserted inline into the existing §3.4 paragraph at line 192 — no lines added or removed, one line modified).

**Changes (one total):**
- §3.4 (Payment Agency, execution paragraph) — insert — added the sentence: "These execution gates are evaluated in a fixed order — the indenture-`ACTIVE` gate first, then the run's distribution-status gate, then the tranche-`ACTIVE` gate, and the funding-sufficiency check only after all three state gates — so a run that violates several state gates at once (for example, a `SUSPENDED` run under a `DEFAULTED` indenture) is rejected with `ERR_INDENTURE_NOT_ACTIVE`." — pins the intra-priority-5 gate order left open by §2.8 rule 5 — `implementation/routes_payments.py:168-178` (indenture gate at 168-170 fires before the distribution gate at 172-174).

Step-7 items 1 and 2 (missing `register_account` / `create_open_solicitation` imports in tests) were pure test-fixture bugs with no PRD silence — no PRD edit. Item 3 was the genuine ERROR-PRECEDENCE-SILENCE and is the sole edit above.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- (a) **Subject:** evaluation/reporting order among the priority-5 state-admissibility gates of `POST /payment-runs/{id}/execute` — the indenture-`ACTIVE` gate (`ERR_INDENTURE_NOT_ACTIVE`) vs the run distribution-status gate and the tranche-`ACTIVE` gate (both `ERR_INVALID_STATE`).
- (b) **Impl paths enumerated and read/grepped:**
  - `implementation/routes_payments.py:158-189` (`execute_payment_run`) — actual gate order: 404 → `ERR_INDENTURE_NOT_ACTIVE` (lines 168-170) → `ERR_INVALID_STATE` distribution (172-174) → `ERR_INVALID_STATE` tranche (176-178) → `ERR_FUNDING_SHORTFALL` (187-189).
  - Grep for `ERR_INDENTURE_NOT_ACTIVE` across all `implementation/*.py`: defined in `errors.py:21`, raised **only** at `routes_payments.py:169` — so the pin is execute-scoped and cannot mis-describe any other endpoint.
  - `routes_payments.py:132-155` (`fund_payment_run`): ownership check (143) then distribution gate (145); no indenture gate — wording scoped to "execution gates" so funding is untouched.
  - `routes_payments.py:248-299` (`reverse_payment_run`): DISTRIBUTED gate (256) + RETURNED-record gate (260); no indenture gate.
  - `routes_payments.py:325-342` (`return_record`): record gates + parent-run-DISTRIBUTED gate (337); no indenture gate.
  - `routes_payments.py:34-110` (`create_payment_run`): tranche-`ACTIVE` gate at line 45 only.
  - `implementation/domain.py:154-198` (default/resume/accelerate/rescind cascades): acceleration (183-189) does **not** suspend runs, so a `SCHEDULED` run under an `ACCELERATED` indenture+tranche also hits the indenture gate first — consistent with the pinned order.
  - `calc.py:90`, `domain.py:299` (settlement skips while DEFAULTED/ACCELERATED): sweep behavior, not request gates — unaffected.
- (c) **Wording adjustment made:** the pin was scoped to execution only ("These execution gates..."), states the full three-gate order plus funding-last (matching lines 168-189 exactly, and consistent with §2.8's priority 5-before-20), and gives the `SUSPENDED`-under-`DEFAULTED` case as an example consequence rather than an exhaustive claim — avoiding any universal statement about other endpoints' state gates, which have no indenture check.

## Step 9: Complete PRD — 2026-08-11T09:17:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1165_corporate_trustee_bond_indenture/workspace/PRD_COMPLETED.md` is written and verified.

**Size delta:** PRD_FINALIZED.md 347 lines / 58,149 chars → PRD_COMPLETED.md 347 lines / 63,075 chars (char-delta +4,892; line count unchanged — all changes are in-paragraph inserts/revisions, no new sections).

**Counts:** 31 ambiguity-pins, 4 mismatch-revisions (35 changes total).

**Change log** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — insert — ambiguity — missing `X-User-ID` never rejected; absent header stored as empty string in attribution fields — auth.py:16
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + twenty random uppercase-alphanumerics — envelope.py:11
- §2.2 — insert — ambiguity — `has_more` true iff `offset` + returned items < `total_count` — envelope.py:25
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer → `ERR_INVALID_REQUEST` — envelope.py:55-79
- §2.3 — insert — ambiguity — per-endpoint filter sets exactly as §4 rows (unfiltered rows: `status`; indentures also `issuer_ref`); exact case-sensitive match; unknown params ignored — envelope.py:82-92, routes_core.py:74-77
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — store.py:60
- §2.4 — insert — ambiguity — no-change write/recompute is not a mutation (no `updated_at`/`version` bump) — store.py:72-80
- §2.5 — insert — ambiguity — clock target unconstrained; backward sets allowed — routes_core.py:24-33
- §2.7 — insert — ambiguity — stale-version check sits between §2.8 rules 5 and 6 on each guarded endpoint — routes_trustee.py:27-29, routes_collateral.py:96-99, routes_defaults.py:146-149
- §2.8 rule 3 — revise — **mismatch** — ownership decided pre-resolution only for payload-declared noteholder accounts; resource-derived ownership (issuer chains, stored endorsement) checked immediately after resolution, so dangling ids report `ERR_NOT_FOUND` first — routes_covenants.py:104-110, routes_payments.py:137-143, routes_defaults.py:274-278
- §2.8 rule 4 — insert — ambiguity — absent/non-string `*_id` fails resolution as `ERR_NOT_FOUND`, ahead of rule-26 required-field check — routes_core.py:118-121, 237-244
- §3.1 — insert — ambiguity — `current_trustee_ref` is null until activation — routes_core.py:59
- §3.1 — insert — ambiguity — tranche creation on any non-DRAFT/ACTIVE indenture (incl. terminal `SATISFIED`) → `ERR_INVALID_STATE` — routes_core.py:122-125
- §3.2 — revise — ambiguity — seed `principal_history` entry's `effective_from` is the logical-clock creation instant — routes_core.py:264-267
- §3.2 — revise — ambiguity — zero-principal transition to `REDEEMED` happens only via redemption execution; zero-principal registration stays `ACTIVE` — routes_payments.py:221-228
- §3.2 — revise — **mismatch** — conservation invariant's sum-over-ACTIVE-positions equality holds provided registered positions summed to full original principal (server maintains original less executed non-reversed redemption allocations) — domain.py:49-57
- §3.3 — insert — ambiguity — initial `next_due_date` equals `period_anchor_date` — routes_covenants.py:69
- §3.3 — insert — ambiguity — roll-forward adds 3/6/12 calendar months with day clamped to month length — domain.py:210-221, validate.py:140-147
- §3.3 — revise — ambiguity — sweep-created case has null `declared_by_user_id`, `cure_deadline` = sweep instant + 30 days; one sweep may fire both rungs (`OPEN`→`LATE`→`BREACHED` in one pass) — domain.py:251-273
- §3.3 — insert — ambiguity — certificate on a `WAIVED` obligation may be accepted but does not roll the obligation forward — routes_covenants.py:188-194
- §3.4 — insert — ambiguity — `REVERSED` run admits no writes; fund/execute/reverse against it → `ERR_INVALID_STATE` — routes_payments.py:145-147, 171-174, 256-258
- §3.4 — revise — ambiguity — funding gate is the numeric `funded_amount_cents >= gross_amount_cents` comparison; zero-gross run executes unfunded — routes_payments.py:186-189
- §3.4 — insert — ambiguity — distribution records created in position `created_at` ascending, ties by `original_principal_cents` descending — routes_payments.py:24-27, 202-210
- §3.4 — insert — ambiguity — `RETURNED` is terminal; re-return → `ERR_ALREADY_TERMINAL` — routes_payments.py:332-335
- §3.4 — insert — ambiguity — reversal appends restored `principal_history` for every recorded position (incl. zero-cent) and returns a `SATISFIED` indenture to `ACTIVE` when a tranche revives — routes_payments.py:271-297
- §3.5 — insert — ambiguity — `CURED` and `WAIVED` are the terminal case states — routes_defaults.py:22
- §3.5 — revise — ambiguity — `threshold_rule` stored verbatim (exact strings for 25%-inclusive and 50%-strict variants) — routes_defaults.py:165-170
- §3.5 — revise — ambiguity — `WITHDRAWN` is terminal for endorsements — routes_defaults.py:280-281
- §3.5 — insert — ambiguity — direction execution requires case in the instruction's source state (`CONFIRMED`/`CONFIRMED`/`ACCELERATED`); terminal case → `ERR_ALREADY_TERMINAL`, else `ERR_INVALID_STATE` — routes_defaults.py:306-316
- §3.6 — insert — **mismatch** — ballot casting returns `201 Created` carrying the updated solicitation (not a new resource) — routes_consents.py:205
- §3.6 — insert — ambiguity — `PASSED`/`FAILED`/`EXPIRED`/`REVOKED` are terminal solicitation states — routes_consents.py:19
- §3.7 — insert — ambiguity — `EFFECTED`/`REJECTED`/`SUPERSEDED` are terminal request states — routes_collateral.py:20
- §3.7 — insert — ambiguity — zero `outstanding_principal_cents` yields `post_release_coverage_bps` of 0 — calc.py:110-112
- §3.8 — revise — **mismatch** — `extraordinary_hours` required for `EXTRAORDINARY_SERVICE` but accepted-and-ignored on `ANNUAL_ADMIN`; fractional hours allowed — routes_fees.py:59-62, calc.py:92
- §3.8 — insert — ambiguity — `VOID` is terminal like `PAID` — routes_fees.py:15, routes_trustee.py:114-117
