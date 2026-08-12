# Worklog — task_1191_grain_cooperative_patronage_member_equity

## Step 1: Create Task Directory — 2026-08-11T16:00:44.000Z

Pre-assigned output folder `tasks/task_1191_grain_cooperative_patronage_member_equity/` and its `workspace/` subdirectory verified to exist. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T16:33:58.000Z

Generated three scaffold artifacts for task 1191 (Grain Cooperative Patronage & Member Equity Revolvement) at "harder than expert" difficulty, saved to `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/`:

**SCAFFOLD.yaml** (79,685 bytes)
- **Complexity profile**: `compliance_audit` (primary) + `ledger_reconciliation` (secondary); 8 complexity layers including optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers
- **13 entities**: Member, DelegateDistrict, Delegate, FiscalYear, GrainDelivery, PatronageAllocation, EquityCertificate, RevolvementCycle, BoardResolution, RedemptionRequest, EstateClaim, UnclaimedEquityLot, PatronTaxForm (hybrid topology, self-referential links on certificates/requests/forms)
- **10 state machines** with cyclic (FiscalYear REOPENED loop), branching (RedemptionRequest appeal cycle), and compound transitions
- **10 calculations** including dual-variant patronage allocation (PROVISIONAL vs FINAL), pinned per-delivery rounding for per-unit retains, tiered rate modifier with boundary semantics, pro-rata waterfall redemption
- **12 validation priorities** spanning auth → existence → state → safety → temporal → referential → constraint → fiscal → boundary
- **67 endpoints** including `/_clock/set_current_utc` test-driving endpoint (default 2026-05-01T00:00:00Z) and full filtered-list GETs for FK reverse-reachability
- **24 error codes** covering OCC (412), state (409), compliance (422), fiscal boundary (422)
- **3 concurrency rules** (member withdraw, fiscal year finalize, certificate disburse) all OCC-based with `expected_*_version`
- **8 roles** including `entity_backed:Member` for Member, opaque for operational roles

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (82,623 bytes)
- 9 rule_ids × 2 instances each = **18 difficulty instances**, all with structured `setup_api_calls` and `trigger` chains, literal-pinned payloads, `${var}` captures threading server-minted IDs, and OCC version inputs referencing prior captures
- Differentiation honored: dual-variant on different entity domains (PatronageAllocation vs Member ledger); combinatorial modes (a) tiered-branch vs (b) rounding-order; non-linear state machines on different entities (FiscalYear cycle vs RedemptionRequest appeal); transitive cascades from different triggers (estate approval depth-4 vs allocation reversal depth-3); priority conflicts on different category pairs (state/fiscal vs safety/referential); boundary checks on different metrics/endpoints (volume tier vs estate window days); cross-entity deps on different pairs (RedemptionRequest→FiscalYear vs EquityCertificate→EstateClaim); temporal overlap with different interval semantics (cycle half-open window vs fixed 30-min appointment slot); invariants on different conserved quantities (patronage pool cents vs certificate face value cents)

**SCAFFOLD_CORNER_DESIGN.yaml** (56,020 bytes)
- 9 sections × **26 corner instances** covering entities (creation/required-fields/retrieval/not-found/computed/system), state machines (invalid transitions, terminal lockdown, precondition enforcement), calculations (constants applied, precision boundaries), validations (auth/RBAC/fiscal boundary), endpoints (pagination, FK reverse-reachability, filtering), errors, RBAC (role denial), cross-cutting layers (OCC stale + correct version, derived field), and consistency (immediate)

**Verification**: All three files exist, are non-zero size, parse as valid YAML, and `scaffold_lint.py` reports `VERDICT: clean lint` with 67 endpoints, 13 entities, 18 difficulty instances, 26 corner instances, 456 calls scanned, 0 violations.

## Step 3: Copy Shared Files — 2026-08-11T16:34:26.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T17:02:00.000Z

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/PRD.md` (50,021 bytes, 320 lines) — generated solely from `SCAFFOLD.yaml`; the two forbidden difficulty/corner design files were not opened or consulted, and no other `task_*` directory was inspected.

**Document structure**: 2-paragraph introduction; §2 with ten subsections (RBAC, verbatim §2.2 response structure, pagination, the cooperative logical clock with its `2026-05-01T00:00:00Z` boot default, common resource properties, nested retrieval, units/money/rounding, OCC, the two equity conservation invariants, and the 12-step validation cascade with explicit priority ordering); §3 with nine domain-grouped workflow subsections (membership/districts, delivery intake, year-close allocation waterfall with tier modifiers and rounding-drift reconciliation, audit/finalize/reopen/tax forms, certificates and revolvement, redemption and pro-rata disbursement, death/withdrawal/expulsion/estates, dormancy/escheat, board resolutions); §4 endpoint table (68 rows, 4 columns, including the `expel` transition whose path the scaffold's state machine nominates but the endpoint table omits); §5 error catalogue (24 codes, 2 columns).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[].request_body/input+output: 56 required, 56 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in §2.10 prose in order, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write operation + expected_*_version + exact error_id + HTTP 412), 0 missing
- state_machines[].transitions: 41 checked across 10 machines, 41 fully expressed, 0 missing
- calculations[]: 10 checked, 10 expressed as precise prose (incl. per-delivery retain rounding order, 8dp half-even pool shares, tier boundaries 1000/10000 inclusive, 70% qualified fraction, 365.2425-day dormancy years, 90-day estate window inclusive, half-open 30-minute appointment windows, both conservation invariants), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose; all 24 error ids appear in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (death cascade, close/finalize/reopen cascades, AMENDED reissue chain, disbursement drawdowns, escheat linkage), 0 missing
- entities[].fields[] structured content: defaults (claim_window_days 90, dormancy_years 5), enum value sets, computed-field derivations all reconstructible from prose, 0 missing
- sibling-branch symmetry: parallel branches (APPROVED/REJECTED, PARTIALLY_REDEEMED/REDEEMED, PROVISIONAL/FINAL variants, per-delivery vs aggregate retain) rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 468
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block verified byte-identical to the canonical source file; all 44 state values, all enum values, and all 8 role names appear verbatim in backticks; no fuzzy/approximating wording; roles' identity semantics (`Member` entity-backed vs seven opaque roles) translated per spec.

## Step 5: Generate Unit Tests — 2026-08-11T17:30:52.000Z

Full test infrastructure generated for task_1191 (grain cooperative patronage/member equity).

**`test_helpers/` (9 files)** — `types.py` (13 entity TypedDicts + 16 status/enum classes), `api_client.py` (ApiClient subclassing `GenericApiClient`, 62 methods covering every endpoint in PRD §4 including the clock driver), `api_errors.py` (24 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity validators + allocation slice identity), `factories.py`, `constants.py` (retain rates 8/10/6/7/9c, tier bounds 1000/10000, 90-day claim window, 1800s slots), `test_users.py` (7 opaque role headers + `make_member_headers` for the entity-backed Member role), `fixtures.py` (composite chains: `setup_year_with_deliveries`, `close_year_provisional`, `finalize_year`, `setup_closed_final_year`, `pass_resolution`, `setup_under_review_request`, `approve_request`, `setup_estate_claim_filed`, `create_and_open_cycle` — with mandatory Member-identity threading).

**`test_suite/` (conftest + 15 files, 61 tests)** — every test carries exactly one resolvable `Design:` tag as its docstring's last line and a verbatim PRD citation (all quotes verified by literal grep of PRD.md; py_compile and `pytest --collect-only` pass: 61 collected, 0 errors).

**Coverage**
- **Queue A (Difficulty): 18/18 instances, 36 tests (exactly 2 each).** No skips.
- **Queue B (Corner): 25/25 non-stub instances, 25 tests (exactly 1 each).** The one stub (`errors/err_not_found_triggerable`) was not translated; its `difficulty_instance` pointer resolves to `member_not_found_returns_404` (covered by the entities test).

**Adjudication notes (PRD-first filter applied)**
- `dual_variant_calc/patronage_allocation_provisional_vs_final_on_member_equity`: the divergence sub-claim is unreachable (PRD exposes no endpoint to adjust audited `net_margin_cents`); the 2 emitted tests cover the PRD-derivable residue (agree-path → FINALIZED with unchanged cents; `final_audit_locked` + tax-form issuance). The divergence assertion stays a gap.
- `cross_entity_state_dependency/redemption_approval_depends_on_fiscal_year_final`: the recipe's literal setup (UNDER_REVIEW against an ISSUED cert) contradicts PRD §3.6 (submit requires ACTIVE certs, which only exist after CLOSED_FINAL). Translated via a reachable equivalent: pass resolution → reopen year (REOPENED ≠ CLOSED_FINAL) → decide must be refused (`validate_error_is_one_of` since PRD pins the rule but not the specific error ID) plus a positive control.
- `state_vs_business_fiscal_on_redemption_disburse`: recipe's over-amount request would fail at creation (ERR_FISCAL at create per §3.6); translated to disburse-on-PENDING / disburse-on-UNDER_REVIEW, preserving the asserted `ERR_INVALID_STATE`.
- Cycle and quorum recipes used placeholder `subject_ref_id`s (would trip §3.9's referential check); reordered to create the cycle/fiscal-year first and reference the real entity.
- Disburse-dependent tests pin the clock to 2050 so `redeemable_at` is reached regardless of the unspecified `min_holding_years` value (a PRD silence).

## Step 6: Generate Implementation — 2026-08-11T17:30:52.000Z

Implementation complete and verified for task_1191 (Grain Cooperative Patronage & Member Equity).

**Files written (all under `.../workspace/implementation/`)**
- `start.sh` — executable; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — flask>=2.2
- `app.py` — Flask app assembly, blueprint registration, `before_request` lazy sweeps (estate-claim lapse at filed+365d, lot aging NOTIFIED→ESCHEAT_PENDING), ApiError/404/405 handlers
- `common.py` — in-memory store (14 dicts, no seeding, no disk I/O), logical clock (boots at 2026-05-01T00:00:00Z), envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), limit/offset pagination (default 10, clamp [1,100], `total_count`/`has_more` in meta), auth (`X-User-Role` + `X-User-ID`, entity-backed Member role), all 24 error IDs with exact HTTP statuses
- `services.py` — patronage waterfall (8dp half-even shares, half-up cents, tier modifiers T1/T2/T3 at inclusive 1000/10000 bushel bounds, rounding drift posted to largest-volume member with earliest-`joined_at` tiebreak), per-delivery per-unit retain rounding (floor net bushels, half-up cents, commodity rate table), pro-rata disbursement (floor + remainder one cent at a time by `issued_at` then `created_at`), certificate lifecycle, tax-form box computation, pool/certificate conservation
- `routes_core.py`, `routes_equity.py`, `routes_governance.py` — all endpoints

**Verification results**
- All 6 `.py` files compile clean; Flask 3.0.3 present
- `bash start.sh` boots to HTTP-ready in <2s; store is empty on boot and stays empty across a kill/restart (per-test-server isolation safe); no seed functions, no SQLite/JSON/pickle/tmp persistence
- 50-check end-to-end smoke test passed 0 failures, covering: auth 401/403, clock set, district/member creation + uniqueness 409s, fiscal boundary 422s, delivery booking/settle (`net=floor(1000×0.9)=900`, retain `900×8=7200`), `ERR_DELIVERY_ALREADY_SETTLED`, provisional close with hand-computed allocation values (pool 800000; m1: cash 201600, qual equity 302400, nonqual 216000, T1), pool conservation to the cent, allocation reversal revoking certs and zeroing member equity, audit → OCC-guarded finalize (412 on stale version), certs ISSUED→ACTIVE with `redeemable_at`, tax form issuance (box1/box3), full redemption flow (request → submit → resolution vote → PASSED → decide → disburse), `ERR_CERTIFICATE_NOT_REDEEMABLE`, `ERR_STALE_CERTIFICATE_VERSION`, partial redemption pro-rata, member equity drawdown, OCC-guarded withdraw, pagination meta
- Route parity: all 67 declared (method, path) pairs from SCAFFOLD.yaml §1.5 are registered (orchestrator independently re-verified: 0 missing). Two intentional extras beyond §1.5: `POST /coop/members/{id}/expel` (declared in PRD §4 + RBAC matrix + state machine — PRD wins) and `POST /coop/revolvement_cycles/{id}/cancel` (declared in §1.2 state machine); plus Flask's built-in `/static` GET.

Notable judgment calls (spec gaps resolved): `min_holding_years` = 1 Gregorian-average year (value not pinned in PRD/scaffold); reconciliation drift posted to the largest member's `nonqualified_allocation_cents` (keeps the pool invariant exact, mirrors "residual goes to equity"); `expected_*` OCC fields required (400 when absent) per PRD §2.8 "must carry".

## Step 7: Run Tests and Iterate — 2026-08-11T17:40:55.000Z

## Summary

- **Iterations run**: 2 (first sweep: 9 failures consistent across all 8 rounds; second sweep: 61/61 in all 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `test_11_disbursement.py::test_final_disburse_completes_redemption` — restructured to submit both redemption requests up-front (while the certificate is still `ACTIVE`) before either disbursement. The original sequence (disburse → create second request → submit) tripped the PRD-required submit-time check "every listed certificate must be ... in `ACTIVE` status" (PRD §3.6) because the first partial disbursement had already flipped the cert to `PARTIALLY_REDEEMED`. Test bug, not implementation bug.

- **Fixes applied to `implementation/`**:
  - `routes_governance.py::record_probate` — changed the early-probate error from `ERR_ESTATE_WINDOW_NOT_ELAPSED` to `ERR_COMPLIANCE_GATE`. PRD §2.10 verbatim: "the estate claim window has elapsed before probate is recorded ... otherwise `ERR_COMPLIANCE_GATE` (HTTP 422). These gates guard ... probate recording." The other error code is reserved by PRD §3.6 for the ESTATE redemption decision path.
  - `routes_equity.py::appeal_redemption_request` — return the original (now `APPEALED`) request from the appeal endpoint instead of the spawned `UNDER_REVIEW` request. PRD §4 row for `/appeal` declares the primary transition "REJECTED → APPEALED; spawns fresh UNDER_REVIEW request"; the response body now matches the primary transition.
  - `routes_equity.py::create_cycle` — removed the `ERR_REFERENTIAL` check on `board_resolution_id` at cycle creation. PRD §2.10 lists referential targets (resolution's `subject_ref_id`, appeal's `appeal_of_request_id`) but does not list cycle's `board_resolution_id`; moreover, the resolution references the cycle (chicken-and-egg), so a faithful reader would not enforce existence at creation. The stored field is preserved.

Relevant absolute paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/implementation/routes_governance.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/implementation/routes_equity.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/test_suite/test_11_disbursement.py`

Final state: 8/8 rounds, 61/61 tests passing per round (orchestrator-verified on disk: all 8 results.*.json show passed=61 total=61 failed=0).

## Step 8: Finalize PRD — 2026-08-11T17:44:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 320 lines, PRD_FINALIZED.md = 320 lines (0% line-count delta; both edits are inline insertions extending existing paragraphs).

### Changes (one bullet per edit)

- **§3.5 (Revolvement cycle planning)** — insert — Pinned that `board_resolution_id` is stored as supplied at cycle creation with no referential existence check (the enabling resolution typically references the cycle in its own `subject_ref_id`, so requiring existence at creation would be circular); §2.10's referential-target list already omits it. — `implementation/routes_equity.py:142-173` (`create_cycle` stores the field, no existence check); cross-checked against `routes_equity.py:201-229` (`open_cycle` validates via `has_passed_resolution('OPEN_REVOLVEMENT', cycle_id)`, which keys off the resolution's `subject_ref_id`, not the cycle's `board_resolution_id`).

- **§3.6 (Redemption appeal)** — insert — Pinned that the `POST /coop/redemption_requests/{req_id}/appeal` response body carries the original request (now `APPEALED`), and the spawned `UNDER_REVIEW` request is persisted but discoverable only via the listing endpoints. — `implementation/routes_equity.py:444-470` (`appeal_redemption_request` returns `success(public(r))` where `r` is the original; the spawned request is written to `db.redemption_requests` but not returned).

### Step 7 items that required no PRD edit

- **`record_probate` error code (`ERR_ESTATE_WINDOW_NOT_ELAPSED` → `ERR_COMPLIANCE_GATE`)** — PRD §2.10 step 7 already states verbatim that the probate-recording gate is `ERR_COMPLIANCE_GATE` (HTTP 422), and §3.6 already reserves `ERR_ESTATE_WINDOW_NOT_ELAPSED` for the ESTATE redemption decision path. The implementation fix brought the code into line with the PRD; prose already correct, kept verbatim.
- **Test-suite restructure in `test_11_disbursement.py`** — pure fixture bug (submit ordering), no PRD silence.

### Per-edit pre-edit search log

**Edit 1 — appeal response body (§3.6)**
- (a) Subject: which resource the appeal endpoint returns in its response body.
- (b) Paths enumerated: grep for `appeal` / `APPEALED` across all of `implementation/` confirmed exactly one appeal route — `routes_equity.py:444-470`. `services.py` contains no appeal helpers. The endpoint mutates the original (`r['status'] = 'APPEALED'`), persists a new request (`db.redemption_requests[new_req['id']] = new_req`), and returns `public(r)` — the original. No other endpoint returns a redemption request derived from an appeal. Also cross-checked §2.2's default return convention ("the created or updated resource object") — both a create and an update happen here, hence the silence; the pin resolves it in favor of the updated path-addressed resource.
- (c) Wording scoped strictly to the appeal endpoint's response body; explicitly notes the spawned request is persisted and reachable through the existing `appeal_of_request_id` list filter (already documented in §3.6's filter list), so no claim is made about any other endpoint. No adjustment needed after enumeration.

**Edit 2 — `board_resolution_id` existence at cycle creation (§3.5)**
- (a) Subject: whether creating a revolvement cycle validates that `board_resolution_id` references an existing resolution.
- (b) Paths enumerated: grep for `board_resolution_id` across `implementation/` — `routes_equity.py:147` (required field), `:159` (parsed), `:170` (stored), `:193` (list filter). No existence check anywhere. Cross-checked `services.py::check_resolution_ref` / `subject_exists` / `has_passed_resolution`: `has_passed_resolution` (used by `open_cycle` at line 208) matches resolutions by `(kind, subject_ref_id, status='PASSED')` — it validates that some PASSED `OPEN_REVOLVEMENT` resolution points at the cycle, not that the cycle's `board_resolution_id` points at anything. Also verified PRD §2.10 step 9's referential-target list (certificate ownership, certificate/allocation year match, resolution `subject_ref_id`, appeal `appeal_of_request_id`) — cycle `board_resolution_id` is absent, consistent with the implementation. Test factory `test_helpers/factories.py:97` confirms with placeholder `"pending-resolution"`.
- (c) Wording deliberately under-determined: says creation runs no referential check on the field, and attributes this to §2.10's list rather than inventing a new rule. Avoids claiming the field is "never validated" (it is never validated anywhere, but the wording only needs to cover creation). Justifies the design (chicken-and-egg with `subject_ref_id`) so a fresh implementer understands why. No conflicting path found; no adjustment needed.

## Step 9: Complete PRD — 2026-08-11T17:56:00.000Z

**Source vs. Completed**
- Source: `workspace/PRD_FINALIZED.md` — 320 lines, 50,717 chars
- Output: `workspace/PRD_COMPLETED.md` — 320 lines, 61,044 chars (char-delta +10,327)

**Counts**
- Ambiguity-pins: 22
- Mismatch-revisions: 4

**Changes (one bullet per edit)**

- §2.3 Pagination — revise — ambiguity — pin clamping direction (limit <1→1, >100→100, offset<0→0), non-integer limit/offset rejected with ERR_INVALID_REQUEST, tie-break identical `created_at` by insertion sequence — common.py:176-196.
- §2.5 Common Resource Properties — revise — ambiguity — pin `version` starts at 1 (was "starts at its initial value") — common.py:142.
- §3.1 Membership — revise — ambiguity — pin `delegate_district_id` nonexistent → ERR_REFERENTIAL; duplicate `patron_ref` → ERR_CONSTRAINT_VIOLATION — routes_core.py:48-51.
- §3.2 Booking — revise — mismatch — pin that `net_bushels` is computed and stored at booking time (PRD said settle time); pin member/fiscal-year existence → ERR_REFERENTIAL; pin compliance gate applies to any non-ACTIVE member (not just DECEASED) — routes_core.py:443-470.
- §3.2 Settlement — revise — mismatch — pin that settle reads the already-stored `net_bushels`; pin settling while year not OPEN → ERR_INVALID_STATE; pin settling CANCELLED → ERR_INVALID_STATE; pin cancelling non-BOOKED → ERR_INVALID_STATE — routes_core.py:528-560.
- §3.3 Fiscal year creation — revise — ambiguity — pin that `patronage_pool_cents` is also computed and stored at creation, and `closed_at`/`final_audit_locked` initialized — routes_core.py:343-356.
- §3.3 Waterfall — revise — ambiguity — pin that `nonqualified_allocation_cents = gross − qualified`, `qualified_equity_issued_cents = qualified − cash`, drift is posted into the target member's `nonqualified_allocation_cents`, and ties on `joined_at` are broken by member creation sequence — services.py:167-191.
- §3.3 Allocation reverse — revise — ambiguity — pin ERR_INVALID_STATE on reversing non-PROVISIONAL or year already CLOSED_FINAL; pin that only certificates not already REVOKED are revoked — routes_equity.py:86-95.
- §3.4 Begin audit — revise — ambiguity — pin ERR_INVALID_STATE on any non-CLOSED_PROVISIONAL source — routes_core.py:392-393.
- §3.4 Finalize — revise — mismatch — pin that only PROVISIONAL allocations are reviewed (AMENDED untouched), that FINALIZED keeps variant=PROVISIONAL, that AMENDED sets variant=FINAL, that certs issued in the year (incl. replacements) flip ISSUED→ACTIVE with `redeemable_at` set, that `closed_at` is re-stamped, and that the per-patron >0 test is over `cash+qualified_equity+nonqualified` — services.py:234-284.
- §3.4 Reopen — revise — ambiguity — pin resolution-gate error mapping (ERR_REFERENTIAL vs ERR_INVALID_STATE), pin that only FINALIZED allocations return to PROVISIONAL (AMENDED untouched), and that only ISSUED tax forms go to VOID — routes_core.py:414-425, services.py:287-298.
- §3.4 Re-finalize after reopen — revise — ambiguity — pin that `corrects_form_id` points at the most recently created VOID form for the same member/year — services.py:315-320.
- §3.4 Tax form — revise — ambiguity — pin that finalization issues forms directly in ISSUED status with `issued_at` stamped, and that `box_4_federal_withheld_cents` is set to 0; pin void-from-non-ISSUED → ERR_INVALID_STATE — services.py:328-332, routes_governance.py:386-388.
- §3.5 Certificates — revise — ambiguity — pin `min_holding_years` = 1 Gregorian-average year; pin the set of statuses counted in member `qualified_equity_cents`/`nonqualified_equity_cents` (ISSUED/ACTIVE/PARTIALLY_REDEEMED/FROZEN) — services.py:26, 40-53, 270, common.py:85.
- §3.5 Cycles — revise — ambiguity — pin `target_year_offset` measured in Gregorian-average years; pin that cycle-open takes no payload but requires an existing PASSED OPEN_REVOLVEMENT resolution with subject=cycle; pin the eligible-certificate assignment rule (matching class + ACTIVE + age ≥ offset); pin cycle-close and cycle-cancel precondition errors → ERR_INVALID_STATE — routes_equity.py:201-255.
- §3.6 Redemption create — revise — ambiguity — pin member existence → ERR_REFERENTIAL; pin that the acting identity must equal `member_id` except for estate executors of DECEASED members (else ERR_FORBIDDEN); pin listed-cert existence → ERR_REFERENTIAL; pin that cert status is not validated at creation — routes_equity.py:278-301.
- §3.6 Submit for review — revise — ambiguity — pin the source-state error code (ERR_INVALID_STATE), the member-status allowance (ACTIVE/INACTIVE/DECEASED) with ERR_INVALID_STATE otherwise, the FROZEN vs other-non-ACTIVE split (ERR_CERTIFICATE_FROZEN vs ERR_INVALID_STATE), the re-check of appointment-not-in-past at submit, and ERR_FISCAL for non-positive amount — routes_equity.py:363-389.
- §3.6 Decide — revise — ambiguity — pin full resolution-kind mapping (incl. SPECIAL_HARDSHIP→APPROVE_SPECIAL_REDEMPTION, CYCLE_REDEMPTION→OPEN_REVOLVEMENT); pin that resolution.subject_ref_id must equal the request id; pin resolution error mapping; pin cycle-OPEN precondition → ERR_INVALID_STATE and the cycle-finding rule (cert's revolvement_cycle_id else any OPEN cycle of matching class); pin ESTATE claim lookup rule; pin issuing fiscal year CLOSED_FINAL → ERR_INVALID_STATE; pin appeal window error → ERR_TEMPORAL_WINDOW; pin appeal-from-non-REJECTED → ERR_INVALID_STATE — routes_equity.py:395-470, services.py:17-22, 352-362.
- §3.6 Disburse — revise — ambiguity — pin `expected_certificate_versions` accepts dict or parallel list; pin malformed-shape → ERR_INVALID_REQUEST; pin cert status must be ACTIVE/PARTIALLY_REDEEMED → ERR_INVALID_STATE; pin pro-rata remainder distribution's final tie-break by creation (insertion) sequence — routes_equity.py:473-511, services.py:365-397.
- §3.7 Deactivate/reactivate/withdraw — revise — ambiguity — pin ERR_INVALID_STATE for each precondition violation — routes_core.py:112-202.
- §3.7 Expel — revise — ambiguity — pin that expel takes no resolution payload but scans for a PASSED APPROVE_SPECIAL_REDEMPTION resolution with subject=member, absence → ERR_INVALID_STATE; pin the set of cert statuses made redeemable (ISSUED/ACTIVE/PARTIALLY_REDEEMED/FROZEN) and that "immediately redeemable" means `redeemable_at` set to now — routes_core.py:205-221.
- §3.7 Record death — revise — ambiguity — pin future `date_of_death` → ERR_TEMPORAL_WINDOW; pin executor missing/not-ACTIVE/not-ESTATE → ERR_REFERENTIAL; pin non-ACTIVE source → ERR_INVALID_STATE — routes_core.py:139-179.
- §3.7 Estate claim — revise — ambiguity — pin `claim_amount_cents` sums certs in (ISSUED, ACTIVE, PARTIALLY_REDEEMED, FROZEN); pin `probate_completed_at` initialized to null; pin probate-not-elapsed → ERR_COMPLIANCE_GATE; pin decide-from-non-PROBATED → ERR_INVALID_STATE; pin resolution-error mapping for APPROVE; pin DENY requires only that the resolution exists; pin that the auto-DISTRIBUTED transition is evaluated after each disbursement — routes_core.py:158-171, routes_governance.py:62-111, services.py:409-424.
- §3.8 Unclaimed lots — revise — ambiguity — pin cert/member referential errors and `dormancy_years` integer check; pin `escheat_eligible_at` computed at creation; pin notify-from-non-DORMANT → ERR_INVALID_STATE; pin escheat resolution error mapping and escheat-from-non-ESCHEAT_PENDING → ERR_INVALID_STATE; pin the certificate-side rule (skip when already REVOKED/ESCHEATED/REDEEMED; zero outstanding; record a disbursement row when outstanding > 0); pin recover identity-mismatch → ERR_FORBIDDEN and recover-from-non-NOTIFIED → ERR_INVALID_STATE — routes_governance.py:115-225.
- §3.9 Resolutions — revise — ambiguity — pin duplicate `resolution_code` → ERR_CONSTRAINT_VIOLATION; pin subject_ref must exist somewhere in the system; pin tabling-from-non-PROPOSED → ERR_INVALID_STATE; pin open_voting-from-non-PROPOSED → ERR_INVALID_STATE; pin accepted `vote` values FOR/AGAINST case-insensitive; pin record-vote-from-non-VOTING → ERR_INVALID_STATE; pin unseated-delegate → ERR_INVALID_STATE and missing delegate → ERR_REFERENTIAL; pin that duplicate votes by the same delegate are counted each time; pin that a quorum-failed tally still records the vote and leaves the resolution in VOTING — routes_governance.py:229-335.
- §4 Endpoints — revise — mismatch — GET `/coop/fiscal_years/{fy_id}`: add ExternalAuditor to allowed roles — routes_core.py:369.
- §4 Endpoints — revise — mismatch — GET `/coop/fiscal_years/{fy_id}/allocations`: add ExternalAuditor to allowed roles — routes_equity.py:44.

**Files relevant to the task**
- workspace/PRD_COMPLETED.md (produced)
- workspace/PRD_FINALIZED.md (source, unmodified)
- workspace/implementation/{common.py, routes_core.py, routes_equity.py, routes_governance.py, services.py} (alignment target)
