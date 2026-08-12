# Worklog — task_0928_daily_money_management_fiduciary

Scenario (verbatim from user): `928. Daily Money Management & Bill-Pay Fiduciary: client intake & authorization, bill-pay & account monitoring, budget & benefit application, bookkeeping & statement reconciliation, fraud/scam alert, bonded/insured & audit trail, family reporting, care-team coordination`

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-08T12:24:30.000Z

Created `tasks/task_0928_daily_money_management_fiduciary/workspace/`. Index 0928 chosen as max existing (`task_0927_home_inventory_valuables`) + 1.

## Step 3: Copy shared files — 2026-08-08T12:24:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0928_daily_money_management_fiduciary/workspace/INSTRUCTION.md` (1424 bytes). Run early since it has no dependency on Step 2.

## Step 2: Generate scaffold — 2026-08-08T13:36:00.000Z

All three scaffold artifacts are generated and lint-clean.

### Files
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

### Scale
| Dimension | Value |
|---|---|
| Entities | **17** |
| Endpoints | **70** (39 POST/ops + 31 GET) |
| State machine axes | **14** — 9 non-linear (Client ACTIVE↔SUSPENDED cycle; ClientAccount fraud_posture re-entrant cycle; Payment `approval_status` cycle **and** `settlement_status` — two parallel axes on one row; ReconciliationPeriod CLOSED→REOPENED→IN_REVIEW→LOCKED plus an IN_REVIEW→OPEN revert; FraudAlert NEW→ESCALATED→ACKNOWLEDGED rejoin; BenefitApplication capped DENIED↔APPEALED loop; FamilyRecipient ACTIVE↔SUSPENDED + ACTIVE→ACTIVE; CoordinationRequest bounded OPEN→OPEN), plus 3 branching-fork (Authorization, Dispute, StatementLine) and 2 linear |
| Calculations | **14**, of which **5 dual-variant** across 5 different entity domains (Payment settlement date projected/effective; BudgetCategory variance full/PTD; SuretyBond exposure committed/settled-inclusive; FraudAlert risk band intake/review; BenefitApplication resources gross/net) |
| Error codes | **36** |
| Validation ladder | **39 rungs** |
| OCC rules | **3** (ClientAccount, ReconciliationPeriod, FamilyRecipient) |
| Conservation invariants | **5** (available-balance identity; ledger-sum identity; budget-line capacity; org-wide bond exposure; disclosure-category closure) |
| Deepest cascade | **6 links** (confirm fraud → account FROZEN → in-flight payment STOPPED → STOP_PAYMENT_FEE ledger entry → period `unreconciled_entry_count` +1 → period IN_REVIEW reverts to OPEN) |
| Declared constants | **62** |
| §1.8 / §1.9 instances | 26 (9 rules × 2–3) / 49 (7 `excluded_because` stubs) |

### Verification
- `yaml.safe_load` — **OK** on all three files.
- `scaffold_lint.py` — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (801 calls scanned).
- Undeclared-constant grep: only `UTILITY_VENDOR`, which is the deliberately invalid enum literal in the ERR_INVALID_ENUM corner test.
- Auxiliary audits: zero unbound `${var}`, zero duplicate instance names across both design files, **all 36 error codes exercised**, all stub `difficulty_instance` targets resolve, zero forbidden concurrency vocabulary.

### Gate precedence (item E)
`G1 bond-expired (6) → G2a authorization-inactive (7) → G2b authorization-scope (8) → G3 account fraud freeze (9) → G4 reconciliation-period freeze (10) → G5 ordinary per-request rungs (11+)`, all after auth/role/existence/shape/enum (1–5). Widest blast radius first. A `period_freeze_exclusions` list names every operation still permitted while frozen (audit reads, fraud alerts and postures, authorization revocation, coordination, report generation, the reopen path itself, retro award posting).

### Self-repairs made during the reachability audit
1. **`ERR_APPEAL_LIMIT_REACHED` was graph-unreachable** — `APPEALED→DENIED_FINAL` made the state gate (rung 12) pre-empt the cap rung (26). Removed `DENIED_FINAL`; a denied appeal returns to `DENIED`, so only rung 26 stops the loop.
2. **`ERR_REOPEN_NOT_PERMITTED`'s count clause was unreachable** — a once-reopened period closes into `LOCKED`, so rung 12 always pre-empts the count check. Rung 23 narrowed to the 30-day window only; the count cap is now documented as structurally enforced.
3. **Rung 12 vs rung 30 ambiguity on release** — the SCHEDULED→IN_FLIGHT transition listed `approval_status == APPROVED` as a precondition, which would have masked `ERR_SECOND_APPROVAL_REQUIRED`. Added a normative `axis_split_note`: rung 12 checks only the axis the trigger advances; the cross-axis check is rung 30.
4. **`variance_direction: OVER` was arithmetically unhittable** — rung 36 guarantees `variance_full_cents >= 0`. Re-keyed `variance_direction` to the period-to-date variant, which legitimately goes negative when spending front-loads.
5. **`LedgerEntry.CANCELLATION_REVERSAL` was a dead enum value** — no transition produced it (cancellation moves no money). Removed, with the rationale recorded.
6. **`Payment.approval_status = PREPARED` is never observable** — documented as a machine entry state resolved inside the same request, so no test asserts it.
7. **Mode-(b) rounding example produced identical results both ways** — retuned `resource_items` to two odd-valued `LIFE_INSURANCE` entries so per-item rounding (205390) differs from sum-then-round (205389) by exactly 1 cent.
8. **The inclusive 3-day duplicate-payment boundary was unhittable via ACH** — business-day projections skip the needed date. Switched the instance to `BILLER_DIRECT` (lead 0), where send dates 2026-06-01 and 2026-06-04 give Δ = 3 exactly.
9. **Arithmetic fix in a corner assert** — cleared balance after a settled 600000-cent payment is 4399100, not 4399500 (tier-3 fee is 900).
10. **YAML lint fixes** — `?`-suffixed optional inputs inside flow sequences (`[status?, limit?]`) break PyYAML; all quoted. `$.data[0].id` inside a flow mapping likewise quoted.

### Orchestrator's independent verification
- `yaml.safe_load` re-run on all three files → OK. Top-level keys of `SCAFFOLD.yaml` confirm **no** `scaffold_difficulty_design` / `scaffold_corner_design` leakage.
- `len(endpoints)` re-counted from the parsed YAML → **70**, matching the subagent's claim.
- Independent ALL_CAPS sweep: 30 constant-shaped tokens; 26 have declared values; the 4 residuals (`NSF_FEE`, `SERVICE_FEE`, `STOP_PAYMENT_FEE`, `ERR_DUPLICATE_PAYMENT_WINDOW`) are LedgerEntry `entry_type` enum members and one error code, not constants — their real constants (`NSF_FEE_CENTS=3500`, `STOP_PAYMENT_FEE_CENTS=3000`, `SERVICE_FEE_TIER{1,2,3}_CENTS=250/500/900`) all carry values. **0 undeclared constants.**

## Step 4: Generate PRD — 2026-08-08T13:56:00.000Z

**Output:** `workspace/PRD.md` — 672 lines / ~20,400 words, written in six bounded increments and re-read end-to-end afterwards.

**Structure:** §1 Introduction (3 paras) · §2 with 13 domain-derived subsections (RBAC & identity, verbatim response envelope, pagination/ordering/filters, logical clock & instant rendering, common properties + version-bump ledger, money & rounding, path resolution, the write gates, the 39-rung ladder, OCC, audit trail, conservation invariants, serialized representations) · §3 with 9 lifecycle subsections · §4 endpoint table (4 columns, all 70 rows) · §5 error table (2 columns, all 36 rows). Document ends at §5 with no audit footer.

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 92 required, 92 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 69 checked (14 axes), 69 fully expressed, 0 missing
- calculations[]: 14 checked (5 dual-variant), 14 fully expressed, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 70 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 150 checked, 150 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (payment approval fork, payment settlement exits, dispute 4 outcomes, period CLOSED-vs-LOCKED, statement-line 4 dispositions, retro-award 2 branches, freeze-sweep hops A–D, client CLOSED from ACTIVE/SUSPENDED, benefit APPROVED/DENIED from SUBMITTED/APPEALED), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1166
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-silence items pinned** (all 10 requested areas): a per-operation **version-bump ledger table** covering all 39 mutating ops plus the three governing principles (derived-aggregate recompute ≠ mutation; a row touched twice bumps once; rejected requests bump nothing; reads never write); per-field-class **timestamp rendering** (three-digit-fraction `Z` instants vs. verbatim-echoed caller dates, with `current_utc` explicitly re-rendered); the **five-gate precedence** with the full permitted-while-frozen list; the **39-rung ladder** as an ordered list with a closed iff-list for `ERR_INVALID_ENUM` ("no other field routes here"); the **Payment parallel axes** with the rung-12/rung-30 split spelled out both ways; **non-firing cascade legs** (supersession ≠ revocation, no cancellation entry type, dispute branches that append nothing, freeze-sweep hop C/D preconditions, the retro-award else-branch); list sort + write-order tie-break + out-of-enum filter → empty page; per-entity **field projections** with the echoed entity named per action endpoint; every boundary marked inclusive/exclusive and the business-day lead pinned to day-zero counting; and all **5 conservation invariants** as integer-cent identities with their assertion point.

**Two judgement calls made where the scaffold was silent** (both pinned explicitly rather than left open): the `AuditEntry.disclosure_category` mapping is rendered as a closed function of `subject_entity` (all 16 values covered), and the three fiscal ceilings on a *revision* are pinned to delta semantics (the payment's own current contribution backed out first), matching the endpoint's "re-runs every fiscal rung on the delta" description. Also softened three role claims where the state machine's `actor` was narrower than the endpoint's role list (approval-decision, statement-line disposition, period status) so that rung 2 remains the only role check.

**Orchestrator's independent verification:** 672 lines; §4 table has exactly **70** method rows; §5 table has exactly **36** `ERR_` rows; leakage grep for `scaffold|difficulty_design|corner_design|test_recipe` → 1 hit, which is the ordinary English phrase "every deadline, window and expiry rule in this scaffold" in the clock endpoint's description — no design-index content leaked.

## Steps 5 + 6: Generate unit tests and implementation (launched CONCURRENTLY in one message) — 2026-08-08T14:25:30.000Z

### Step 5 — unit tests (subagent summary, verbatim)

Test infrastructure and suite are complete.

**Output**
- `test_helpers/` — 9 modules (~2,400 lines): `types.py`, `api_client.py` (all 70 endpoints), `api_errors.py` (36 codes + status map registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`
- `test_suite/` — `conftest.py` + 11 test files (~3,700 lines)

**Coverage**

| Queue | Instances | Translated | Skipped | Tests |
|---|---|---|---|---|
| A (Difficulty) | 26 | **26** | 0 | 53 (every instance ≥2) |
| B (Corner, non-stub) | 42 | **42** | 0 | 42 (every instance ≥1) |
| B stubs (`excluded_because`) | 7 | n/a — not translated | — | 0 |

**Total: 95 tests, 95 `Design:` tags** (exactly one per `def test_`, zero untagged, zero dual-tagged, zero pointing at a non-existent or stub instance). All 7 stub cross-references were verified to resolve to real difficulty-design instance names. **No instance was skipped** — every one passed the PRD-first two-condition filter.

**Input deviation (device 2) — one made**

`corner_available_balance_boundary_permits_a_payment_that_lands_exactly_on_zero`
- Original recipe assert: *"a second **identical** create against the same account would return `ERR_INSUFFICIENT_AVAILABLE`"*
- Substituted: a second create naming a **different payee** for **1000 cents** (instead of the same payee at 80000).
- Two readings the original admitted: an identical re-create shares account + payee + `amount_cents` with a still-`SCHEDULED` payment whose projected date is 0 days away, so the duplicate-payment buffer (rung 19) fires **before** account sufficiency (rung 37) — one reader returns `ERR_DUPLICATE_PAYMENT_WINDOW`, another `ERR_INSUFFICIENT_AVAILABLE`. The substitution makes rung 19 unreachable while preserving the instance's actual claim (available balance of exactly 0 refuses the next disbursement) verbatim.

**Verification results**
- **`py_compile` over the whole tree: PASS** (all 9 helper modules + 12 suite files).
- `pytest --collect-only`: **95 tests collected**, no import errors.
- **PRD-citation sweep: 158 citations, 0 verbatim failures** — every quoted span survives a whitespace-normalised literal match against `workspace/PRD.md` (5 initial mismatches were hyphen-vs-em-dash and were corrected to the PRD's exact characters).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere. No "scaffold" / `§1.x` / "Table N" leakage in generated code.

**Devices applied**
1. **Semantic instant comparison** — `parse_instant()` / `assert_same_instant()` / `assert_instant_offset()` in `assertions.py` parse both sides to aware datetimes; used for every `ack_due_at`, `executed_at`, `released_at`, `closed_at`, `created_at` assertion. Exact-string rendering (`assert_instant_rendering`) is used only in the clock-default test, where PRD §2.4 states the `.mmmZ` rendering rule verbatim and the claim *is* about rendering.
3. **Gate discipline** — `setup_billpay_world()` is the single baseline: bond IN_FORCE across the clock date, ACTIVE client with a capacity finding, ACTIVE instrument spanning the clock date, account at `NORMAL` posture, and **no reconciliation period at all** so G4 passes for want of a receiving period. Each gate test perturbs exactly one of those.
- **Distinct identities** — `test_users.py` gives every principal its own `X-User-ID` (`u-mgr`/`u-mgr2`, `u-spec`/`u-spec2`, `u-comp`/`u-comp2`, `u-care1..4`), with mandatory per-instance builders `make_client_headers(client_id)` and `make_family_recipient_headers(recipient_id)` for the two `entity_backed` roles. Segregation-of-duties tests use preparer `u-spec` vs approver `u-comp`, and the SoD violation is exercised via `make_fiduciary_manager_headers("u-spec")` — same natural person, different role.

All arithmetic in the design indices (settlement-date stages, fee bands, per-item resource rounding, proration, fraud scores, retro months, dispute day counts) was independently recomputed before being written into assertions and matched the yaml literals exactly.

### Step 6 — implementation (subagent summary, verbatim)

The implementation is complete and verified.

**Location:** `workspace/implementation/`

**Structure:** 28 Python files (26 modules + 2 `__init__.py`), **3,903 lines**, plus `start.sh` and `requirements.txt`. Split as `core/` (errors, constants, clock, store, envelope, pipeline/ladder, calc, aggregates, gates, audit, serialize) + `routes/` (14 blueprint modules by resource group). Every file written in bounded increments.

**url_map completeness gate: declared 70 / routed 70 / MISSING 0 / EXTRA 0** (paths normalized to `{}` placeholders; Flask's `/static` excluded).

**Bug 1 — timestamp rendering (PRD §2.4), adjudicated per field class**
- **Server-written instants** → `YYYY-MM-DDTHH:MM:SS.mmmZ`, three fractional digits *always*, read off the **logical clock**: `created_at`, `updated_at`, `api_request_timestamp`, `executed_at`, `revoked_at`, `released_at`, `closed_at`, `acknowledged_at`, `consent_recorded_at`, `generated_at`, `recorded_at`, and both `ack_due_at` (clock + whole hours). `current_utc` is **re-rendered**, never echoed — `…09:00:00Z` in returns `…09:00:00.000Z`.
- **Caller-supplied dates echoed byte-for-byte, never re-rendered**: `effective_date`, `expiry_date`, `requested_send_date`, `value_date`, `line_date`, `determined_on` (→ `capacity_determined_on`), `decision_date`, `award_effective_date`, `date_of_birth`, `budget_month`, `period_month`, `report_month`. A DEPOSIT's `entry_date` is the caller's `value_date` verbatim; a non-frozen benefit award's `entry_date` is the caller's `award_effective_date` verbatim.
- **Server-derived dates** → plain `YYYY-MM-DD` / `YYYY-MM` from the logical clock or the computation: `activated_on`, `closed_on`, `submitted_on`, `filed_on`, `settled_on`, `projected_settlement_date`, `effective_settlement_date`, server-dated `entry_date`, `retro_period_month`.

**Bug 2 — enum routing (PRD §2.9 rung 5), closed iff-list**
One shared helper (`Ctx.check_enum` / `check_enum_list`) is called on **exactly** these and nothing else: `scope_tier`, `account_type`, `payee_type`, `channel`, dispute `reason_code`, fraud-alert `reason_code`, `program`, `resource_items[].item_type`, `relationship`, `permitted_categories[]`, `requested_categories[]`, coordination `tier`, `determination`, `to_status` (client/authorization/period), `to_posture`, `adjustment_type`, `decision`, `event`, `action` (statement-line/fraud-alert/benefit-status/coordination), `outcome` (dispute-resolve/record-decision). Every other bad value — numeric range, format, required-missing, element structure, query filters — is `ERR_VALIDATION`; filters are never an error at all.

**Gate/ladder ordering**
Implemented as one ordered evaluation path per handler, rungs annotated in ascending numeric order: 1 auth → 2 role (incl. the CareCoordinator assigned-member check on ACKNOWLEDGE, raised at the role rung via a pre-existence peek) → 3 existence (path L-to-R, then body in the endpoint's input order; Client→`ERR_CLIENT_NOT_FOUND`, all else `ERR_RESOURCE_NOT_FOUND`) → 4 shape (+ the six conditionally-required fields) → 5 enum → **6 G1 bond → 7 G2a authorization → 8 G2b scope → 9 G3 account freeze → 10 G4 period freeze** → 11 client-active → 12 state (payment axis-split: release-requires-APPROVED deferred to rung 30) → 13/14 referential → 15 value constraints (incl. present-but-empty conditionals) → 16 uniqueness → 17 date spans → 18–28 temporal/business → 29 SoD → 30 second approval → 31 capacity → 32 disclosure → 33 scope ceiling → 34 OCC → 35 bond → 36 budget → 37 account → 38 program limits → 39 credit cap. Verified live: `ERR_BOND_EXPIRED` → `ERR_AUTHORIZATION_INACTIVE` → `ERR_ACCOUNT_FROZEN` → `ERR_PERIOD_FROZEN` on the same request as each blocker is cleared; `ERR_SCOPE_NOT_PERMITTED` beats `ERR_SCOPE_AMOUNT_EXCEEDED`; existence beats every gate; `ERR_ACCOUNT_FROZEN` beats `ERR_STALE_VERSION`.

**Constraints confirmed**
- **In-memory only** — plain dicts in `core/store.py`. `grep -rE "sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()"` returns **only two prose comments containing the word "seeded"**; no code hits.
- **No seeding** — store empty on every boot (verified: `total_count` 0 for payments and ledger entries on two independent cold boots).
- **Logical clock authoritative** — starts at `2026-05-01T00:00:00Z`, moved only by `/_clock/set_current_utc`, drives every deadline, window, expiry, cut-off, settlement projection and `api_request_timestamp`. Verified the default is restored on a fresh boot after being advanced.
- Conservation invariants hold by **recomputing each aggregate from its source population** rather than incrementing in place; version bumps follow the §2.5 table exactly (touch-twice-bump-once; rejected requests bump nothing but the audit entry).

**Boot test:** `bash start.sh` boots on a free port and serves within ~1s; killed and re-launched from scratch identically (double-boot script passed). `python3 -m py_compile` clean on all files.

**Behavioural verification:** ~180 live assertions across four smoke suites (envelope/pagination/ordering, all 14 calculations, all 14 state-machine axes, the 6-link revocation cascade, the 4-hop freeze sweep incl. hops C/D, payee-block sweep, supersession-preserves-vs-revocation-destroys, both settlement-date variants with cut-off/weekend/lead boundaries, dispute round-trip exactness, retro-award into a closed month, all 3 OCC rules, the disclosure wall and audit projection) — **0 failures**.

Two adjudications worth flagging: (1) `POST /dmm/reconciliation-periods/{id}/statement-lines` is treated as a **create** for audit purposes (`subject_entity: StatementLine`, `subject_id` = new id / null on refusal), since §4 lists it among the fifteen creation endpoints and §2.13 says it echoes the StatementLine — both readings map to `ADMINISTRATION` so disclosure filtering is unaffected. (2) `GET /dmm/family-reports/{id}` applies the recipient ownership check from §2.1's explicit "generating **or reading** a report for any other recipient is refused"; the analogous check is *not* applied to `GET /dmm/clients/{id}` or `GET /dmm/family-recipients/{id}`, where the row *is* the principal rather than a resource referencing it, and §2.9 rung 32's applies_to is exhaustive.

### Orchestrator's isolation + integrity verification

Step 5 finished ~110 s **before** Step 6, so `test_suite/` and `test_helpers/` were on disk during impl-gen's final stretch (overlap window ~14:05→14:25). Containment checked in the direction that matters:
- grep of `implementation/` for `test_helpers|test_suite|conftest|pytest|api_client|factories|fixtures|test_users` → **0 hits**.
- grep of `implementation/` for test-only principal literals (`u-mgr`, `u-spec`, `u-comp`, `u-care[0-9]`, `setup_billpay_world`, `make_*_headers`) → **0 hits**. This is the sharp check: had impl-gen read the suite, its fixtures' identity constants are what would have bled in.
- Reverse-direction grep of the suite for impl module names returned 18 hits, all ordinary domain words (`payments`, `clients`, `fraud`, `family`, `reconciliation`, `clock`, `constants`) that are URL path segments and domain vocabulary — not evidence of leakage.
- Persistence/seeding sweep over `implementation/` for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()|open(` → **0 hits**.
- `def test_` = **95**, `Design:` tags = **95**, `pytest.mark.skip/xfail/skipif` = **0**, `py_compile` over all 3 trees → OK.

**Verdict: no isolation breach.** Step 7 is briefed on the overlap anyway.

## Step 7: Run tests and iterate — 2026-08-08T14:38:00.000Z

All 8 rounds passed on the first sweep, and the isolation audit found no breach.

**Iterations run: 1.** The 8-round stability sweep came back 95/95 in every round on the first attempt — no failures, no errors, no flakiness, no union set to triage. The diagnostic protocol (STEP 0–3) therefore had no input, and the substantive work was the isolation audit.

**Tests deleted: none.** No test failed in any round, so no test was subjected to the STEP 1 coverage / unique-derivability test.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.**

### Isolation audit

The orchestrator's containment check (re-verified): **0** hits inside `implementation/` for `test_helpers|test_suite|pytest|conftest`, and **0** for the test-only principal ids (`u-mgr`, `u-spec`, `u-comp`, `u-care*`, `u-admin`), `setup_billpay_world`, or `make_*_headers`.

The second half — assertions that could only have been written by reading the implementation:

- **Timestamps — clean.** 108 instant-shaped literals across the test artifacts; 95 are `set_clock(...)` *inputs*, and 13 are assertion call-sites: 10 `assert_same_instant` + 1 `assert_instant_offset` (both parse both sides before comparing) and 2 `assert_instant_rendering`. **0 exact-string instant equality assertions.** The 2 rendering assertions check the regex shape `YYYY-MM-DDTHH:MM:SS.mmmZ`, which PRD §2.4 states verbatim, so they are legitimate.
- **Positional list assertions — clean.** 6 call-sites. Five are immediately preceded by `assert len(entries) == 1` (or read a single-entry fixture list), so no ordering rule is load-bearing. The sixth (`test_11:92`) asserts only that two `limit=1` pages differ, which any total order satisfies. PRD §2.3 pins the ordering verbatim anyway.
- **Exact-`version` assertions — clean.** 4 call-sites, each tracing to a specific PRD §2.5 ledger row: Client created at 1 and stays at 1; ClientAccount created at 1; deposit → `ClientAccount +1` (2); schedule a payment → `ClientAccount +1` (3).
- **Response-field names — clean.** 152 distinct field-ish tokens extracted from every subscript, `.get()`, and membership test. 139 are response fields and **all 139 appear verbatim in PRD.md**. The 13 non-matches are all internal fixture dict keys, never response fields.

Three extra checks added, since a passing suite gets no other scrutiny:
- **158 PRD quotes** cited in test docstrings; **all 158 verbatim in PRD.md** (whitespace-normalized). None fabricated.
- **36 asserted error ids**, all present in PRD.md. **0 `skip`/`xfail` markers** anywhere.
- **Endpoint set identical**: live Flask `url_map` (70 rules) diffs byte-for-byte against the PRD §4 routing table (70 rows).

Cardinal-rule spot-checks on the implementation also came back clean: **no** `datetime.now`/`utcnow`/`time.time`/`date.today`, **no** sqlite/pickle/json-dump/`/tmp`/file-write persistence, **no** seeded or hardcoded entity data at startup.

### Per-round results

| Round | Passed/Total | Failed | Errors | Wall clock |
|---|---|---|---|---|
| 1 | 95/95 | 0 | 0 | 80.1s |
| 2 | 95/95 | 0 | 0 | 79.1s |
| 3 | 95/95 | 0 | 0 | 77.4s |
| 4 | 95/95 | 0 | 0 | 78.2s |
| 5 | 95/95 | 0 | 0 | 104.5s |
| 6 | 95/95 | 0 | 0 | 104.9s |
| 7 | 95/95 | 0 | 0 | 104.5s |
| 8 | 95/95 | 0 | 0 | 104.2s |

Wave 2 (rounds 5–8) runs ~26s slower than wave 1 uniformly — host scheduling under 4-way concurrency, not a per-test regression. Each `round.N.log` contains the expected single benign `Killed` (pre-boot server swap for test #1). The EADDRINUSE respawn flake did not appear in any round.

### Orchestrator's independent zero-fix verification

A clean first sweep is indistinguishable from a false-clean, so every claim above was re-derived from the artifacts rather than trusted:
- All 8 `results.N.json` re-parsed independently → **95 individual test rows each** (not an aggregate counter), status distribution `{'passed': 95}` in every round, and sorted test-name lists **byte-identical to round 1 in all 7 comparisons** (catches a round that silently collected a smaller suite).
- `def test_` count in `test_suite/` = **95** = the runner's collected count.
- Independent route diff, booting the app in-process and comparing `app.url_map` against the scaffold's `endpoints[]` with path params normalized to `{}`: **declared 70 / routed 70 / MISSING 0 / EXTRA 0**.
- `find implementation/ test_suite/ test_helpers/ -newer results.1.json` → **empty**, so the green result describes exactly the tree that shipped.

## Step 8: Finalize PRD — SKIPPED — 2026-08-08T14:40:00.000Z

Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 could have exercised, so there is no `<step_7_diff>` to patch and no `PRD_FINALIZED.md` is produced. Step 9 starts from `PRD.md` and does the whole completeness job.

## Step 9: Complete PRD — 2026-08-08T14:57:00.000Z

`workspace/PRD_COMPLETED.md` is written.

**Files:** `PRD.md` 672 lines / 145,719 chars → `PRD_COMPLETED.md` 672 lines / 165,739 chars (**+20,020 chars**, 54 hunks / 57 lines). Every change is an in-paragraph insert or revision — no lines added or removed, no new sections, all three tables intact (70 endpoint rows, 36 error rows, 43 version-ledger rows).

**Counts:** 45 ambiguity-pins, 12 mismatch-revisions.

### Mismatches: "PRD asserts an enforcement no endpoint performs" (the highest-value findings)

1. **§2.1 Client ownership** — PRD: "ownership checks on *any* resource that references a `Client` compare the resource's client-owning field to `X-User-ID`". Only `POST /dmm/family-recipients/{id}/consent` performs it (`routes/family.py:89`). `GET /dmm/clients/{id}` (`routes/clients.py:141-145`) admits the `Client` role and returns whatever client the path names, with no comparison. Revised.
2. **§2.1 FamilyRecipient ownership** — PRD asserts the check on "any resource that references a `FamilyRecipient`". Performed on exactly three endpoints (`family.py:122`, `family.py:215`, `clients.py:199-202`); `GET /dmm/family-reports`, `GET /dmm/family-recipients` and `GET /dmm/family-recipients/{id}` (`family.py:184-198,201-207`) apply no projection at all. Revised.
3. **§2.9 rung 12** — PRD: "Applies to every mutating operation that names an existing row in its path." Four path-addressed mutations have no from-state check: capacity-determination (`clients.py:47`), account adjustments (`accounts.py:61`), budget override (`budgets.py:61`), statement-line import (`reconciliation.py:59`). Report generation likewise ignores `subscription_status` (`family.py:103`). Revised.
4. **§2.9 rung 5** — PRD: "A malformed or out-of-domain value in any field not on this list is `ERR_VALIDATION` at rung 4." No endpoint validates any date's *format* at rung 4; only authorization/bond `effective_date`/`expiry_date` are syntax-checked, and at rung 17 (`authorizations.py:57-65`). Revised at rungs 4, 17, 24.
5. **§2.8 G4** — PRD resolves the disposition's receiving period from "the period named in the path"; the path names the *line* (`reconciliation.py:143,149`). Revised.
6. **§2.9 rung 32 applies-list** — omitted reading one family report, which `family.py:215` does enforce. Revised.
7. **§3.5 re-score, "Nothing else changes"** — `disposition_note` is written on an `ACKNOWLEDGE` too (`fraud.py:83-84`). Revised.
8. **§3.7 "A `RESOLVE_WRITTEN_OFF` records the `exception_note`"** — it assigns unconditionally, so an omitted note *clears* the flagged one (`reconciliation.py:195`). Revised.
9. **§2.5 / §3.3** — bond exposure and budget variance are *stored*, refreshed only by writes; a clock move into a new month does not refresh them (`aggregates.py:97-114`). Revised.
10. **§3.1 activation** — `activated_on` written only on `INTAKE`→`ACTIVE`; reinstatement never rewrites it (`clients.py:98-108`). Revised.
11. **§3.8 `account_id`** — required and existence-resolved on both outcomes, consulted only by an approval, never cross-checked against the application's client (`benefits.py:139,169-174`). Revised.
12. **§3.5 CONFIRM_FRAUD** — bypasses the posture transition table, writes no `fraud_posture_reason`, and re-freezes an already-`FROZEN` account (`fraud.py:98-103`, contrast `accounts.py:141-148`). Revised.

### Ambiguity pins, by section

- **§2.2** — `api_request_id` = `req_` + 20 upper-alnum chars *(envelope.py:20-21)*
- **§2.3** — non-numeric `limit`/`offset` fall back to the default, not a boundary *(envelope.py:57-68)*
- **§2.4** — `entry_date` is caller-supplied for `DEPOSIT` and ordinary-branch `BENEFIT_AWARD`, server-dated otherwise; `retro_period_month` echoes caller characters *(aggregates.py:130-149, benefits.py:191-208)*; clock accepts partial instants and numeric offsets, normalizes to UTC *(clock.py:22-43, ops.py:20-25)*
- **§2.5** — stored derived figures lag the clock until a write recomputes them
- **§2.7** — a body identifier that is absent/null/mistyped is skipped at rung 3 and surfaces at rung 4 *(pipeline.py:121-132)*
- **§2.9 r4** — explicit `null` counts as absent; a missing/non-object body is an empty object *(pipeline.py:28-45,87-91)*
- **§2.9 r22** — a payment with null `settled_on` fails *here*, not with `ERR_INVALID_STATE` *(disputes.py:55-57)*
- **§2.9 r24** — an unparseable date fails here as `ERR_RETRO_LOOKBACK_EXCEEDED` *(benefits.py:165-167)*
- **§2.10** — OCC compares against the pre-bump version
- **§2.11** — concrete path in `operation`; raw headers in `actor_*`; path-value `subject_id` even on 404; create beats path-addressing for the statement-line import; `client_id` null when refused pre-resolution; unmatched route/method → 404 with **no** audit entry *(audit.py:37-55, pipeline.py:137-156, app.py:50-56)*
- **§2.13** — `resource_items` normalized to `item_type`/`value_cents` only *(benefits.py:75-77)*; global rule that omitted optional free text is never nulled *(payments.py:260, disputes.py:148, fraud.py:83, coordination.py:94)*
- **§3.1** — capacity determination has no from-state gate and is re-recordable; `note` discarded; `to_status` `INTAKE`/`DRAFT`/`EXPIRED`/`SUPERSEDED` → `ERR_INVALID_STATE`; `revocation_reason` non-empty judged after trim, stored untrimmed *(clients.py:47-62,80-96; authorizations.py:84-99)*
- **§3.2** — `value_date` required and freeze-gated on holds then discarded; unreadable `value_date` → null `period_id`; adjustments ignore client status; budget derived figures computed at create; unreadable `budget_month` prorates as fully elapsed; override reason untrimmed, `added_cents` tested first *(accounts.py:61-98, budgets.py:41-83, calc.py:59-75)*
- **§3.3** — malformed `requested_send_date` passes rung 20 and is treated as absent but stored verbatim; approval `note` discarded; revision `memo` replaces only when supplied *(payments.py:95-98,178-181,260-261; calc.py:39-54)*
- **§3.4** — `return_reason` sent with a `SETTLE` is ignored; cancel `reason` discarded; stop fee with no period for the month writes a null-`period_id` entry and moves no counter *(payments.py:316-336,378, aggregates.py:183-197)*
- **§3.5** — alert never cross-checks payment against account; posture `reason` required on every destination and written every time, length untrimmed; freeze-swept payments keep a null `stop_reason`; hop C/D skipped with no period, and the fee posts into `CLOSED`/`LOCKED` books *(fraud.py:26-55, accounts.py:107-148, aggregates.py:202-209)*
- **§3.6** — provisional credit takes no body; disputed amount compared to the payment's *current* `amount_cents`; `resolution_note` preserved on omission *(disputes.py:51,82,148)*
- **§3.7** — null-`period_id` entries move no counter and never revert `IN_REVIEW`; `period_month` unvalidated, adoption *sets* rather than raises the counter; import raises only `imported_line_count` and never reverts a period; reopen keeps `closed_at`; `to_status` `OPEN`/`LOCKED` → `ERR_INVALID_STATE` *(aggregates.py:160-171, reconciliation.py:39-56,89-139)*
- **§3.8** — `award_monthly_amount_cents` has no value constraint (zero/negative accepted onto the ledger); an award landing outside every period still posts *(benefits.py:176-208)*
- **§3.9** — consent refused from `SUSPENDED`/`TERMINATED`; `permitted_categories` stored canonically ordered and deduped; report generation ignores subscription status, so a suspended recipient still sees its retained categories; unreadable `report_month` → 0 disbursed and provisional; assigned-member check is below existence; `reassign_to_user_id` blank-trimmed at rung 15 above the reroute cap; audit projection applied before the filters *(family.py:83-98,128-149; coordination.py:59-92; clients.py:199-206)*

### Orchestrator's independent verification
- `PRD_COMPLETED.md` re-measured: 672 lines / 165,739 chars vs `PRD.md` 672 / 145,719 → **+20,020 chars at zero line delta**, consistent with in-paragraph-only edits.
- Integrity after the 54 hunks: **70** endpoint rows, **36** `ERR_` rows, **28** section headers (identical to `PRD.md`), and the file ends on the final error-table row — no truncation, no duplicated section.
- `PRD_FINALIZED.md` correctly **absent** (Step 8 skipped).
- Re-ran `find workspace/implementation test_suite test_helpers -newer results.1.json`: the only hits are `results.{5,6,7,8}.json`, which are wave-2 sweep *outputs*. **No source file changed after the green sweep**, so the shipped tree is exactly the tree that passed 95/95 × 8.

---

# Pipeline complete

| Step | Status |
|---|---|
| 1 Task directory | done |
| 2 Scaffold | done — 17 entities / 70 endpoints / 39-rung ladder, 10 self-repairs |
| 3 Shared files | done |
| 4 PRD | done — 672 lines / ~20.4k words |
| 5 Unit tests | done — 95 tests, 95 `Design:` tags, 0 instances skipped |
| 6 Implementation | done — 28 modules / 3,903 lines, 70/70 routes |
| 7 Test + iterate | **clean first sweep — 95/95 × 8 rounds, 0 fixes** |
| 8 PRD finalize | skipped (zero fixes) |
| 9 PRD complete | done — 45 ambiguity-pins + 12 mismatch-revisions |
