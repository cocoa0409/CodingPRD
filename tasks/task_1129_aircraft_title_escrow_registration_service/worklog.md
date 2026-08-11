# Worklog — task_1129_aircraft_title_escrow_registration_service

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Task directory `tasks/task_1129_aircraft_title_escrow_registration_service/` and its `workspace/` subdirectory were pre-assigned and already exist; the Step 1 auto-index scan was skipped per pipeline instructions. Difficulty parameter: "hard than expert level" (to be passed to prd-bench-scaffold-generator at Step 2).

## Step 2: Generate scaffold — 2026-08-10T22:19:00.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

**Domain**: Aircraft title/escrow/registration service (Oklahoma City agent) — FAA filing sequence DAG, lien payoff coordination with lenders, trustee ownership structures, logical-clock-driven staleness sweeps, OCC-guarded money movement with segregation of duties.

**Complexity profile**: primary `compliance_audit`, secondary `workflow_orchestration`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint; flat topology; segregation_of_duties role model; immediate consistency.

**Counts**:
- Entities: **11** (Aircraft, Party, EscrowFile, TrustAgreement, TitleSearch, Lien, LienRelease, Deposit, DisbursementInstruction, Filing, ClosingDocument)
- State machines: **10** (incl. Filing with parallel `status` × `verification_status` dimensions; cyclic machines on Filing, TrustAgreement, TitleSearch, Lien; compound/posture-driven EscrowFile)
- Endpoints: **58** (incl. `POST /api/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`)
- Calculations: **5** (tiered escrow fee w/ trust surcharge + floor + cap; dual-variant DAILY/MONTHLY proration; pinned-order closing statement; dual-variant FLAT/PER_DIEM payoff; lien priority ranking with created_at tie-break)
- Validations: **29** ordered rows; Errors: **29** (all referenced); Roles: **4** (LenderRep is `entity_backed:Party`); Concurrency rules: **3** (OCC on EscrowFile.version for deposits, disbursements, close)
- Difficulty instances: **18** (9 rules × 2, all §0.5 differentiation clauses honored — different entity domains, modes {a}/{c}, error-category pairs, metrics, entity pairs, interval semantics, conserved quantities, cascade depths 3 and 2)
- Corner instances: **58** (48 active + 10 `excluded_because:` stubs citing difficulty instances)

**File sizes**:
- `SCAFFOLD.yaml` — 68,410 bytes (826 lines); §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 58,233 bytes (517 lines); single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 111,486 bytes (1,051 lines); single key `scaffold_corner_design`

**Verification performed**:
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (680 calls scanned, 0 violations)
- All formula-derived assert literals executed in Python and confirmed (e.g., DAILY proration 50411 vs MONTHLY 49998; fee 500060 on proration-inclusive base; PER_DIEM payoff 545000/645000; due 250560553; seller net 249000000)
- Name uniqueness across both design files (76 names, no duplicates); all `grounds:` refs resolve; all `excluded_because` targets exist; no forbidden concurrency vocabulary; every error code is triggerable.

## Step 3: Copy shared files — 2026-08-10T22:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1129_aircraft_title_escrow_registration_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T22:25:00.000Z

All audits pass. The "constants not mentioned by name" is intentional — the skill explicitly encourages unit conversion (e.g., "100 hours" instead of `THRESHOLD: 6000` minutes) so constants appear as dollar amounts / day counts rather than as scaffold identifiers.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1129_aircraft_title_escrow_registration_service/workspace/PRD.md`

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles (§2.1 RBAC; §2.2 API Response Structure; §2.3 Pagination; §2.4 Logical Clock and Lifecycle Sweeps; §2.5 Common Resource Properties; §2.6 Nested Resource Retrieval and Path Resolution; §2.7 Optimistic Concurrency Control on the Escrow File; §2.8 Money, Precision, and Frozen Computations; §2.9 Escrow Posture and Cascading Consistency)
- §3 Business Logic & Workflows (§3.1 Onboarding Aircraft and Parties; §3.2 Opening the Escrow File (with §3.2.1 Closing Proration and §3.2.2 Escrow Fee Schedule); §3.3 Title Search and Lien Discovery (with §3.3.1 Lien Priority Ranking); §3.4 Lien Release Coordination; §3.5 Funding the File; §3.6 Disbursement Instructions and Segregation of Duties; §3.7 Owner-Trust Agreements; §3.8 Closing Documents and Signature Logistics; §3.9 Registry Filings and Post-Closing Verification; §3.10 Close, Hold, Cancel, and the End of the File)
- §4 Endpoint Definitions (4-column table, 58 endpoints)
- §5 Error Code Catalogue (2-column table, 29 errors)

**Line count:** 329 lines.

**Coverage audit results:**
- Contract 1 (Field-Name Coverage): PASS. 80 required field names; 80 present in backticks; 0 missing. One repair iteration: `status` added to §2.5 as a narrative sentence describing the per-entity lifecycle field.
- Contract 2 (Rule Coverage): PASS. 29 validations (all `error_id`s in PRD prose); 3 concurrency rules; 10 state machines / 46 transitions; 5 calculations; 29 errors; 58 endpoints all covered.
- Contract 3 (§3 Path Purity): PASS. 534 backticked tokens scanned inside §3; 0 path/method leaks.

**Adjudication decisions:**
- Converted numeric constants to natural units (e.g., `TIER1_CAP: 50000000` → "$500,000 (that is, 50,000,000 cents)").
- Chose 9-subsection §2 and 10-subsection §3 organized by lifecycle stage.
- Repaired one Contract-1 gap: `status` narrative sentence in §2.5.
- Did not read either of the forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`).

## Step 5: Generate unit tests — 2026-08-10T22:55:00.000Z

Test generation is complete. Verbatim summary:

**78 tests total** across 11 test files (all collect cleanly under pytest; zero skips/xfails anywhere).

- **Queue A (Difficulty)**: 32 tests covering 16 of 18 instances, every emitted instance with exactly 2 tests.
- **Queue B (Corner)**: 46 tests covering 46 of 48 non-stub instances (1 test each).
- **Stubs**: 10 `excluded_because:` stubs not translated; all 10 cross-references verified to resolve to real difficulty instances.

**Skipped instances (PRD-first two-condition filter)**

| Instance | Queue | Reason |
|---|---|---|
| `Difficulty/priority_pair_validation_conflict/p1_release_state_beats_fiscal` | A | validation-priority silence: PRD §3.6 states both the file-state gate and the fiscal gate but never commits which error fires when both hold; two faithful readers diverge. |
| `Difficulty/priority_pair_validation_conflict/p2_filing_sequence_beats_liens` | A | validation-priority silence: §3.9 names both `ERR_FILING_SEQUENCE_VIOLATION` and `ERR_LIENS_OUTSTANDING` but pins no precedence between them. |
| `Corner/entities/e_create_with_computed_field_returns_invalid_request` | B | No verbatim PRD sentence states that unknown/computed input fields are rejected (two readers diverge: strict-schema 400 vs. ignore-unknown 201). |
| `Corner/cross_cutting_complexity_layers/x_list_filter_by_status` | B | PRD §2.3/§4 document only `limit`/`offset` list params; a `status` filter on `GET /api/liens` is never stated, so filtered-composition assertions are not PRD-covered. |

**File list (bytes)**

test_helpers/ — `__init__.py` 1043, `api_client.py` 10889 (64 endpoint methods), `api_errors.py` 3102 (29 error IDs registered with framework), `assertions.py` 6943, `constants.py` 1321, `factories.py` 4479, `fixtures.py` 17143, `test_users.py` 1789, `types.py` 7769.

test_suite/ — `conftest.py` 696; `test_01_file_creation_and_validation.py` 9319 (7); `test_02_closing_math.py` 12155 (10); `test_03_security_rbac.py` 8809 (7); `test_04_title_search_and_liens.py` 8137 (7); `test_05_lien_releases_payoff.py` 11756 (8); `test_06_funding_deposits.py` 8042 (7); `test_07_disbursements.py` 9953 (8); `test_08_close_hold_cancel.py` 10734 (9); `test_09_trust_agreements.py` 7706 (5); `test_10_filings_documents.py` 11516 (9); `test_11_aircraft_lookup_and_listing.py` 4026 (3).

**Lint / stage-check results**

- `py_compile` on all 21 files: OK.
- pytest `--collect-only`: 78 tests collected, 0 errors.
- Tag audit: every test has exactly one `Design:` tag as the last docstring line; all 78 tags resolve to real instances; all 16 emitted difficulty instances ≥2 tests; all 46 emitted corner instances ≥1 test: STAGE_CHECK_OK.
- Verbatim citation pass: 127 quoted PRD sentences extracted from docstrings; every one survives literal whitespace-normalized grep of `workspace/PRD.md`: ALL_CITATIONS_VERBATIM_OK (3 initial failures fixed).
- No scaffold/§1.x references in generated code; no `pytest.mark.skip`/`skipif`/`xfail`.

One judgment call: timestamp assertions on `closed_at`/`effective_at` compare the 19-char prefix (`YYYY-MM-DDTHH:MM:SS`) rather than the full string, because PRD does not pin the fractional-digit format for those entity-specific fields.

## Step 6: Generate implementation — 2026-08-10T22:55:00.000Z

All checks pass. Complete summary:

**File List (24 files under `workspace/implementation/`)**: `start.sh` 263, `requirements.txt` 12, `app.py` 1591, `db.py` 2214, `errors.py` 1801, `response.py` 1388, `middleware.py` 1489, `validators.py` 2035, `routes/__init__.py` 0, `routes/aircraft.py` 2914, `routes/clock.py` 3974, `routes/deposits.py` 5428, `routes/disbursements.py` 9108, `routes/documents.py` 6200, `routes/escrow_files.py` 12161, `routes/filings.py` 11379, `routes/liens.py` 3632, `routes/parties.py` 1688, `routes/releases.py` 8377, `routes/title_searches.py` 8306, `routes/trust_agreements.py` 8404, `services/__init__.py` 0, `services/calculations.py` 4050, `services/escrow.py` 8872.

**Endpoint Count**: 58 unique method+path endpoint registrations covering all 58 endpoints defined in the PRD Section 4 endpoint table (1 clock, 3 aircraft, 2 party, 10 escrow file, 4 title search, 6 lien, 5 release, 4 deposit, 6 disbursement, 7 filing, 7 trust agreement, 3 document).

**State Machine Count**: 10 state machines implemented, matching the scaffold — EscrowFile (10 states, automatic bubble-ups CLEARED/FUNDED/RECORDED/VERIFIED and FUNDED→CLEARED revert), TitleSearch (ACTIVE/COMPLETED/STALE with clock sweep), Lien (DISCOVERED/DISPUTED/RELEASE_PENDING/RELEASED with orphan return), LienRelease (7 states with clock-sweep expiry), Deposit (RECEIVED/RETURNED), DisbursementInstruction (PENDING_APPROVAL/APPROVED/RELEASED/VOIDED with segregation of duties), Filing (QUEUED/SUBMITTED/ACCEPTED/REJECTED/WITHDRAWN + parallel verification_status NONE/PENDING/MATCHED/MISMATCHED), ClosingDocument (PREPARED/OUT_FOR_SIGNATURE/PARTIALLY_SIGNED/FULLY_SIGNED), TrustAgreement (DRAFT/SUBMITTED/ACCEPTED/REJECTED/EXPIRED with cyclic REJECTED→DRAFT), Aircraft (REGISTERED/DEREGISTRATION_PENDING/DEREGISTERED/EXPORTED driven by filing side effects).

**Calculation Implementations**:
1. closing_proration DAILY: days strictly after `expected_close_date` through Dec 31 inclusive; `round_half_up(annual_fee * days / 365)`; single final Decimal ROUND_HALF_UP.
2. closing_proration MONTHLY: `full_months = 12 - close_month`; per-month `round_half_up(annual_fee/12)`; half-month credit `round_half_up(annual_fee/24)` if day ≤ 15; per-month rounding then sum.
3. escrow_fee_schedule: 3-tier bps on base = purchase_price + proration; tiers 30/20/10 bps with per-tier half-up rounding; floor 150,000; trust surcharge 75,000; cap 2,500,000.
4. closing_statement_totals: frozen at creation (proration, fee, due); live-recomputed funded/balance/seller_net on deposit create/return and disbursement release/void.
5. effective_lien_payoff: FLAT returns quoted; PER_DIEM `days = min(elapsed, max_days)` capped by good_through_date.
6. lien_priority_ranking: 3 classes concatenated (IR_INTEREST by ir_registered_at, FAA_RECORDED by filed_at, STATE/JUDGMENT by filed_at), created_at tie-break, 1-based rank, recomputed on lien creation.

**Boot Verification Results**: `bash start.sh` starts Flask in foreground via `exec python3 app.py`; reads `$PORT` (default 10000), binds `0.0.0.0`; dependency install guarded; store starts completely empty (no seeding); logical clock starts at exactly `2026-05-01T00:00:00Z` and never falls back to wall clock; full happy-path workflow verified end-to-end (aircraft → parties → escrow file → title search → CLEARED → deposit → FUNDED → close → CLOSED → filings → RECORDED → verify → VERIFIED); error paths verified (ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_NOT_FOUND, ERR_DUPLICATE_N_NUMBER, ERR_STALE_VERSION, ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_FORBIDDEN_IDENTITY, ERR_SEGREGATION_OF_DUTIES); lien release, trust agreement, document signing, and cancel cascade workflows verified.

**Route parity check (orchestrator)**: all 58 (method, path) pairs declared in SCAFFOLD.yaml are registered in the implementation; 0 missing, 0 extra.

## Step 7: Run tests and iterate — 2026-08-10T23:05:00.000Z

**Iterations run:** 2 (initial sweep: 74/78 in all 8 rounds, same 4 tests failing deterministically; post-fix sweep: 78/78 × 8 rounds, zero failures).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**

- `test_suite/test_08_close_hold_cancel.py` — `test_trust_expiry_blocks_close_with_posture_not_ready`: the setup called `setup_basic_file` (which opens a file on the aircraft) and then opened a second file on the same aircraft, which PRD §3.2 forbids ("An aircraft may be the subject of at most one non-terminal file at a time") — the implementation correctly rejected it with `ERR_AIRCRAFT_UNDER_CONTRACT`. Rebuilt the setup inline: aircraft + parties + trustee with no file, accept the trust first, then open the single `requires_trust=True` file (also fixed a leftover `ctx["buyer"]` reference).
- `test_suite/test_10_filings_documents.py` — `test_duplicate_signature_rejected`: with a one-signer required set, the first signature lands the document in terminal `FULLY_SIGNED`, so the duplicate attempt trips both PRD §3.8's "duplicates are rejected with `ERR_ALREADY_SIGNED`" and "`FULLY_SIGNED` is terminal" — PRD names both rules but pins no precedence (error-precedence silence; unlike the quote-window case, a state-first reading does not dead-code `ERR_ALREADY_SIGNED` since duplicates remain reachable from `PARTIALLY_SIGNED`). Relaxed the exact-error assertion to the sanctioned `validate_error_is_one_of([ERR_ALREADY_SIGNED, ERR_INVALID_TRANSITION])` plus an explicit 409 status check (both errors are 409).

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/releases.py` — `create_release`: moved the quote-window check (`ERR_QUOTE_WINDOW_OPEN`, PRD §3.4) before the lien-state gate. A QUOTED release with an open window implies the lien is `RELEASE_PENDING`, so the previous state-first ordering made the PRD-named error unreachable in exactly the scenario PRD describes.
- `workspace/implementation/routes/clock.py` — TitleSearch staleness sweep: changed from date-granularity (`new_date > eff.date() + 30d`) to instant-granularity (`dt > eff + timedelta(days=30)`), per PRD §2.4 "whose `effective_at` lies strictly more than 30 days in the past" — a 1-second overflow past exactly 30 days must sweep to `STALE`.
- `workspace/implementation/routes/escrow_files.py` — `close_escrow_file` freshness gate: same instant-granularity fix for the close-time "on or before `effective_at` plus 30 days, inclusive" check (PRD §3.10), keeping it consistent with the sweep semantics.

**Orchestrator verification:** all 8 `results.{1..8}.json` files exist; every round reports passed=78, total=78, failed=0.

## Step 8: Finalize PRD — 2026-08-10T23:11:00.000Z

PRD_FINALIZED.md is written. The diff is exactly 4 line-replacements, all inline within existing paragraphs — no new sections, no restructuring.

**Line counts:** PRD.md 329 lines; PRD_FINALIZED.md 329 lines; 0% line-count delta (4 of 329 lines modified in place, ~1.2% of lines touched; character delta +1.1%).

**Step_7_diff items disposition:** The `test_08_close_hold_cancel.py` fix was a pure fixture bug (test setup violated PRD §3.2's already-pinned one-non-terminal-file rule, enforced at `implementation/routes/escrow_files.py:95-97`) — no PRD edit. The other four items each produced one edit:

- **§3.4 — revise** — Appended precedence sentence: the quote-window check is evaluated before the lien-state gate, so requesting a release while a same-lien `QUOTED` release's window covers today always yields `ERR_QUOTE_WINDOW_OPEN`, never the generic invalid-transition error — `implementation/routes/releases.py:66-75`.
- **§3.8 — insert** — Added the sign endpoint's status gate: signatures are accepted only in `OUT_FOR_SIGNATURE`/`PARTIALLY_SIGNED`; attempts against `PREPARED` or terminal `FULLY_SIGNED` are rejected with `ERR_INVALID_TRANSITION`, evaluated before the signer-level checks, so a duplicate against a `FULLY_SIGNED` document yields `ERR_INVALID_TRANSITION`, not `ERR_ALREADY_SIGNED` — `implementation/routes/documents.py:135-148`.
- **§3.3 — revise** — Changed the staleness boundary from date-granularity ("a date strictly later than") to instant-granularity ("remains fresh through the exact instant `effective_at` plus 30 days... an instant strictly later") — `implementation/routes/clock.py:47-54`.
- **§3.10 — revise** — Close-time freshness gate: "the current logical date is on or before" → "the current logical instant is on or before `effective_at` plus 30 days, inclusive" — `implementation/routes/escrow_files.py:272-279`.

**Per-edit pre-edit search log:**

1. **§3.4 edit.** (a) Subject: error precedence in `POST /api/liens/{id}/releases`. (b) Enumerated/read: full `create_release` (`releases.py:48-99`); grep confirming `ERR_QUOTE_WINDOW_OPEN` raised nowhere else; `liens.py:93,113`; `services/escrow.py:216-231` + `clock.py:93-104`; `releases.py:213-221` — together proving the edit's "necessarily in RELEASE_PENDING" invariant. (c) No wording adjustment needed; deliberately left "today's logical date" date-granular phrasing intact since `create_release` compares dates (`releases.py:66-71`), not instants.
2. **§3.8 edit.** (a) Subject: validation precedence in `POST /api/documents/{id}/sign`. (b) Enumerated/read: `documents.py:121-159`, `create_document:53-96`, `send_document:99-118`; grep of `FULLY_SIGNED`/`signed_party_ids`/`PARTIALLY_SIGNED`/`OUT_FOR_SIGNATURE` across impl. (c) Adjustment by omission: did NOT pin the relative order of `ERR_ALREADY_SIGNED` vs `ERR_SIGNER_NOT_REQUIRED` — mutually exclusive by invariant; wording scoped strictly to the status gate with the FULLY_SIGNED-duplicate worked example matching `documents.py:135-144`.
3. **§3.3 edit.** (a) Subject: TitleSearch 30-day freshness boundary granularity. (b) Enumerated/read: `clock.py:47-54`, `escrow_files.py:264-279`, `title_searches.py:96-99,158-160`; grep of `effective_at`/`timedelta`/`STALE`; boundary tests in `test_08_close_hold_cancel.py:113-148`. (c) Adjustment: revised only the two boundary clauses; explicitly did not touch §2.4's date-granular `QUOTE_EXPIRED`/`EXPIRED` sweep wording or §3.4's date-granular record gate (`clock.py:60,73`; `releases.py:205-208`).
4. **§3.10 edit.** (a) Subject: close-time search-freshness comparison granularity. (b) Same enumeration as edit 3: `escrow_files.py:272-279` admits equality and rejects any strictly later instant. (c) Adjustment: single-term change date→instant, keeping "on or before ... inclusive".

No other PRD text was altered; §2.4 was left verbatim because its existing wording already determines the instant-granularity sweep the implementation exhibits.

## Step 9: Complete PRD — 2026-08-10T23:24:00.000Z

PRD_COMPLETED.md is produced at `workspace/PRD_COMPLETED.md` — 24 minimal inline edits over PRD_FINALIZED.md, no new sections.

**Size delta**: PRD_FINALIZED.md 329 lines / 56,653 chars → PRD_COMPLETED.md 333 lines / 61,965 chars (+4 lines, +5,312 chars).

**Counts**: 22 ambiguity-pins (PRD silent, inserted impl behavior), 4 mismatch-revisions (PRD described different behavior; revised to impl). Two edits carry both (counted by their dominant character below).

Changes, one per bullet:

- §2.2 — insert — ambiguity — pinned strict body validation: non-object body / missing required / unknown field / bad type-range-enum-date → `ERR_INVALID_REQUEST`; absent body treated as `{}`; bodiless action endpoints ignore bodies; clock reads only `to_iso8601` — `implementation/validators.py:8-44`, `routes/clock.py:24-27`.
- §2.3 — revise — mismatch — "rejects anything above 100" → impl clamps `limit` into [1,100], floors `offset` at 0, non-integer values fall back to defaults (10/0) — `routes/escrow_files.py:36-49` (same `_parse_limit/_parse_offset` in every list route).
- §2.3 — insert — ambiguity — sort ties on equal `created_at` preserve insertion order (logical clock makes ties common) — e.g. `routes/escrow_files.py:171`.
- §2.3 — insert — ambiguity — pinned exact-match conjunctive filter params per list endpoint (escrow-files, liens, deposits, disbursements, filings, trust-agreements) — `routes/escrow_files.py:150-169`, `routes/liens.py:55-70`, `routes/deposits.py:134-143`, `routes/disbursements.py:217-229`, `routes/filings.py:294-306`, `routes/trust_agreements.py:212-221`.
- §2.4 — insert — ambiguity — clock-set performs no monotonicity check (may move backward); missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — `routes/clock.py:24-39`.
- §2.7 — revise — mismatch — "the server ignores one if presented" → strict validation rejects a stray version field with `ERR_INVALID_REQUEST` — `validators.py:27-33`.
- §2.7 — insert — ambiguity — pinned OCC evaluation order: deposit/disbursement writes validate fields and referenced-resource existence before the version compare; close compares version right after body validation, before the §3.10 business preconditions — `routes/deposits.py:56-72`, `routes/disbursements.py:59-94`, `routes/escrow_files.py:244-256`.
- §2.8 — insert — ambiguity — initial live figures at file creation: `total_funded_cents`=0, `escrow_balance_cents`=0, `seller_net_proceeds_cents`=price+proration−fee — `routes/escrow_files.py:123-125`.
- §2.9 — insert — ambiguity — trust coverage interval is inclusive on both ends (`effective_date` ≤ today ≤ `expiry_date`) — `services/escrow.py:33-37`.
- §2.9 — insert — ambiguity — cancel cascade stamps `returned_at` on returned deposits — `services/escrow.py:160-164`.
- §3.2 — insert — ambiguity — file-open references must resolve else `ERR_NOT_FOUND`; `party_type` of named parties is not validated — `routes/escrow_files.py:77-92`.
- §3.3 — insert — ambiguity — `findings` array may be empty (clean search, `finding_count` 0) — `routes/title_searches.py:86-100`.
- §3.3 — insert — ambiguity — findings `lienor_party_id`: missing party → `ERR_NOT_FOUND`, existing non-LENDER → `ERR_INVALID_REQUEST`; `ir_registered_at` merely not required for non-IR types — `routes/title_searches.py:206-216`.
- §3.3 — insert — ambiguity — refresh also leaves `completed_at` untouched — `routes/title_searches.py:155-160`.
- §3.4 — revise — mismatch — "when the basis is FLAT, `per_diem_cents` is omitted" → must be omitted, supplying it → `ERR_INVALID_REQUEST`; pinned `quoted_payoff_cents`/`per_diem_cents` strictly positive — `routes/releases.py:139-152`.
- §3.4 — revise — mismatch — PRD implied every lapsed-window release is swept; pinned that the sweep touches only `QUOTED` releases and recording a `FILED` release past its window → `ERR_INVALID_TRANSITION` — `routes/releases.py:204-208`, `routes/clock.py:57-67`.
- §3.4 — insert — ambiguity — per-diem elapsed-day count floored at zero (record before `quote_date` possible via backward clock) — `services/calculations.py:87-91`.
- §3.5 — insert — ambiguity — deposit `payer_party_id` must reference an existing `Party` else `ERR_NOT_FOUND` — `routes/deposits.py:66-68`.
- §3.6 — insert — ambiguity — disbursement: `payee_party_id` must exist else `ERR_NOT_FOUND`; unresolvable/wrong-file `lien_id` → `ERR_NOT_FOUND`; `lien_id` on non-LIEN_PAYOFF → `ERR_INVALID_REQUEST` — `routes/disbursements.py:74-90`.
- §3.6 — insert — ambiguity — closing-statement body carries exactly seven pinned money fields — `routes/escrow_files.py:291-309`.
- §3.7 — insert — ambiguity — trust create: missing aircraft/trustee → `ERR_NOT_FOUND`; non-TRUSTEE trustee → `ERR_INVALID_REQUEST` — `routes/trust_agreements.py:63-70`.
- §3.7 — revise — mismatch — revise validates the merged date pair (unsupplied side keeps stored value) and clears `submitted_at` unconditionally, not only when dates supplied — `routes/trust_agreements.py:192-202`.
- §3.8 — insert — ambiguity — `required_signer_party_ids` may be empty; such a document can never reach `FULLY_SIGNED` — `routes/documents.py:70-80,143-148`.
- §3.9 — insert — ambiguity — DEREGISTRATION registry-status gate miss → `ERR_FILING_SEQUENCE_VIOLATION`, lien check evaluated first — `routes/filings.py:90-105`.
- §3.9 — insert — ambiguity — resubmit is gated by the same CLOSED/RECORDED file-state requirement and re-evaluates the DEREGISTRATION lien/registry gates too — `routes/filings.py:245-253`.
- §3.9 — revise — ambiguity — `sequence_index` pinned as count of successful submit operations (initial submits and resubmissions) per file, starting at 1 — `db.py:61-64`, `routes/filings.py:169,257`.
- §3.10 — insert — ambiguity — close evaluates the OCC check first of the four preconditions; "latest" search = most recently created — `routes/escrow_files.py:244-279`.
- §3.10 — insert — ambiguity — holding an already-`ON_HOLD` file → `ERR_FILE_ON_HOLD`; cancel clears `hold_return_state` to null — `routes/escrow_files.py:185-186,226-227`.
- §4 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — `app.py:46-53`.

Deliberately left unpinned as unobservable: dispute/resolve-dispute omit the CLEARED bubble-up, but DISPUTED and DISCOVERED both block posture, so no flip to READY is reachable from those actions (`routes/liens.py:87-124` vs `services/escrow.py:88-93`).
