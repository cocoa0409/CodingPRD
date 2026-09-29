# Worklog — task_2631_statement_composition_print_mail_bureau

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2631_statement_composition_print_mail_bureau` and its `workspace/` subdirectory. Index was pre-assigned (2631) by the invoking pipeline; no scan of ./tasks/ was performed, per instruction, to avoid collision with the ~32 concurrent pipelines on this host.

## Step 2: Generate Scaffold — 2026-09-04T00:33:00.000Z

All three artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2631_statement_composition_print_mail_bureau/`
- `SCAFFOLD.yaml` — 3,066 lines / 167 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,874 lines / 210 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,120 lines / 292 KB

All three parse with `yaml.safe_load`. `SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys); the two design files each have a single top-level key.

**§1.0–§1.7 counts**: 15 entities, 9 state machines, 2 concurrency rules (`reprint-create-stale-job` on CompositionJob, `batch-seal-stale-client-escrow` on Client), 13 calculations, 42 ordered validations (priority ladder 1→80), 64 endpoints, 54 errors, 6 roles. Profile: `workflow_orchestration` / `compliance_audit`, graph topology, parallel state machines, layers `cascading_side_effects, dual_variant_calculation, optimistic_concurrency, selector_policy`, `segregation_of_duties` role model, `immediate` consistency.

**§1.8** — 9 rule ids, 24 instances: dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (3), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (3), cross_entity_state_dependency (3), resource_temporal_overlap (2), compensating_invariant (3).

**§1.9** — 92 instances (65 with full `test_recipe`, 27 `excluded_because` stubs) across all nine guide sections: entities 15 (2 stubs), state_machines 17 (6), calculations 19 (6), validations 12 (3), endpoints 10 (4), errors 8 (1), rbac 4 (0), cross_cutting_complexity_layers 5 (4), consistency_model 2 (1). All 116 instance names are globally unique across both design files; every stub cites a real §1.8 instance name and carries no `test_recipe`.

**Verification**
- `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (64 endpoints, 15 entities, 24 §1.8 + 65 §1.9 instances, 1,376 calls scanned)
- Error coverage: all 54 catalog ids are triggered by at least one non-stub instance.
- All `grounds` tokens resolve to real entities/fields/errors/calculations/roles/concurrency rules.

**Adjudications / repairs made this session**
- Added `matched_piece_count`, `missing_scan_count`, `duplicate_scan_count`, `reprint_chain_depth` to CompositionJob (persisted by `one_to_one_integrity_reconciliation`, reset by reprint) so the integrity-summary read is a pure read of stored counters.
- Deleted two structurally unreachable validations (`ERR_JOB_INTEGRITY_BREACH`, `ERR_JOB_BATCHES_OPEN`) and their catalog entries: close requires MANIFESTED, which is only reachable from VERIFIED with every batch MANIFESTED. Errors 56→54, validations 44→42.
- Reprint OCC re-worded to fire at priority 40 (after the piece-level gates), matching the ladder.
- The reprint OCC 412 is only reachable via a *second* hold cycle (reconcile #1 → reprint → reconcile #2 → INTEGRITY_HELD), because nothing else bumps the job version while it is held; the cross-cutting instance is built that way.
- `delivery_channel` lives on StatementRecord, not MailPiece, and DrSite is a singleton with no collection listing — two §1.9 captures rewritten accordingly; CompositionJob records no `closed_by_user_id`, so the SoD close assertion now keys on `status` + `billing_total_cents`.
- `selector_policy` is an active complexity layer with no claim-extraction-guide row; its claim is filed as a `cross_cutting_complexity_layers` stub deferring to the §1.8 selector instance, with the EXPLICIT-vs-SELECTED behaviour covered by a real `endpoints` instance.
- The hygiene 0.90 band boundary is unreachable (city is a required non-empty field), so band-representative values are asserted instead of an exact-edge case.

Orchestrator verification: `ls -la` + `wc -l` + `yaml.safe_load` on all three files confirm existence, size and parse; top-level keys are as specified.

## Step 3: Copy Shared Files — 2026-09-04T00:33:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T00:48:00.000Z

PRD.md is complete and verified.

## Output

`workspace/PRD.md` — **479 lines / 111,995 chars.** Ends at a completed §5 Error Code Catalogue (54th row, `ERR_POSTAGE_ESCROW_INSUFFICIENT` | 402) — no truncation. Built via 16 chunked appends; no single giant Write.

## Section list (23 headings)

§1 Introduction
§2 Global Specifications — 2.1 Operator Identity and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Semantics · 2.5 Left-to-Right Path Resolution and Body Reference Resolution · 2.6 Numeric Precision, Basis Points and Rounding · 2.7 OCC on Escrow and Reprint Writes · 2.8 Segregation of Duties on Postage Liability and Commercial Closure · 2.9 Conservation Invariants Across the Three Ledgers · 2.10 Rejection Precedence · 2.11 Disaster-Recovery Readiness Posture
§3 Business Logic & Workflows — 3.1 Client Registration, Commercial Terms, Postage Funding and the Suppression File · 3.2 Template Families, Regulatory Insert Stock and Variable Content Rules · 3.3 Data File Receipt, Format Validation and Control Reconciliation · 3.4 Composition: Address Hygiene, Channel Resolution, Sheet Build and Insert Reservation · 3.5 Presort Qualification and Batch Materialisation · 3.6 Press Floor Scheduling, Line Selection and Run Execution · 3.7 Barcode Scanning, One-to-One Integrity and Reprints · 3.8 Postage Escrow, Entry-Facility Manifesting, Closure and Invoicing · 3.9 Undeliverable Return Processing and Address-Update Feedback
§4 Endpoint Definitions (64 rows) · §5 Error Code Catalogue (54 rows)

## Hard Contracts — all PASS

- **Contract 1 (Field-Name Coverage):** entity fields 175 required / 175 present / **0 missing**; endpoint body+query inputs 87 required / 87 present / **0 missing**. Also verified: 54/54 `errors[].id`, 88/88 enum+state values, 6/6 role names.
- **Contract 2 (Rule Coverage):** all 42 `validations` (each check + its explicit priority position, surfaced as a 14-step ordered Rejection Precedence list in §2.10), all 9 state machines (every transition, precondition and side effect, including the two parallel MailPiece dimensions and the depth-4 abort cascade), all 13 calculations, both concurrency rules, and every `endpoints[].side_effects` bullet are expressed in prose.
- **Contract 3 (§3 Path Purity):** 1,186 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens.

Other checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; `grep -in "harder than expert\|expert level\|difficulty\|test_recipe\|scaffold"` returns nothing. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

## Adjudications (7 scaffold-internal conflicts)

1. **Role identity** — `complexity_profile` comments and two state-machine preconditions hint `ClientLiaison` is entity-backed and scoped to its own Client, but `roles[].identity` is `opaque` for all six and no error code or validation exists for a liaison-ownership failure. Resolved for `opaque`: §2.1 states `X-User-ID` is never compared to any entity `id` and participates only in the two segregation-of-duties checks.
2. **`Client.status` mutability** — entity constraint says "settable at creation only", but `PATCH /bureau/clients/{id}` lists `status?` and its description names "commercial standing". Resolved for the endpoint: `status` is amendable.
3. **`amend-control-totals` variance handling** — endpoint side_effects say "clear every variance counter to 0"; state-machine side_effects say "recompute against the amended declarations". Resolved for recompute (clearing to 0 isn't derivable since actual counts are not reset): `format_error_count` → 0, every record's `format_valid` → false, three variance figures recomputed against the amended declarations.
4. **`imb_barcode` "compact" `received_at`** — pinned as fourteen digits `YYYYMMDDHHMMSS`, no separators, with `piece_seq` zero-padded to six digits.
5. **`reprint_index`** — pinned as depth in the reprint chain: first replacement of an original is suffixed `-R1`; a replacement of that replacement appends `-R2` to its own predecessor's barcode.
6. **Scan rejection precedence** — pinned as `UNKNOWN_BARCODE` → `DUPLICATE_STAGE` → `OUT_OF_SEQUENCE`, matching the conjunct order of the scaffold's "accepted when" clause.
7. **`ERR_TEMPLATE_INVALID_STATE`** — `errors[]` names only "not DRAFT", while validation priority 31 and the transition precondition add the higher-`version_no` ACTIVE-sibling check. Both conditions are stated.

Two gaps found and repaired during verification: `disposition` was prose-only in §3.9 (now backticked, closing the last Contract 1 hole), and the `validate-format` `RECEIVED`-only state gate was implicit (now explicit with `ERR_FILE_INVALID_STATE` 409). A §2.3 paragraph enumerating every listing's exact-match filter parameters and their conjunctive combination was also added.

Orchestrator verification (guarding the known doc-generator truncation failure): `wc -l` = 479, `wc -c` = 111,995, `tail -c 1200` shows the §5 table terminating on a complete final row at a real section boundary — not mid-sentence. Heading scan shows all 23 sections present in order. Difficulty-instruction leak grep returns nothing.

## Step 6: Generate Implementation — 2026-09-04T01:29:00.000Z

The implementation is complete, compiles, and passes an end-to-end smoke test.

## Modules (all in `workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `app.py` | 72 | Flask app factory, per-request id, `ApiError`/`HTTPException`/catch-all handlers (404 `ERR_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`), blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | 498 | Logical clock (starts exactly `2026-08-01T00:00:00Z`, never wall clock), in-memory `Store` (15 dicts + `_seq`), envelope/meta/`respond`/`respond_list`, all 54 error ids -> HTTP status, auth (`X-User-ID`/`X-User-Role`, 6 roles), request-shape validators, pagination + enum-validated filters, half-up rounding, `ceil_div` |
| `calc.py` | 306 | Every enum tuple + all 13 calculations: record format check, control-total variance bp, hygiene confidence/disposition, sheet composition with variable-content rules, IMb minting, gross/net postage, press requirements + selection score, run-window sizing, window conflicts (buffer both sides), utilization bp, SLA severity/projected/assessed penalty, volume-discount tiers, 8-step billing, DR readiness |
| `domain.py` | 220 | 404 lookups per entity, contractual ordering helpers, `apply_changes` (version bumps only on real change), piece/batch/line counter recomputation, insert & press-sheet ledger moves, integrity-hold minute crediting |
| `routes_ref.py` | 555 | Clock, clients (+ deposits, paperless-sync, address-feedback, sub-lists), templates (+ activate cascade), insert stocks, press lines, entry facilities, DR site (singleton, drills, PATCH) |
| `routes_intake.py` | 277 | Data files (validate-format, control-check, amend-control-totals), statement records, paperless enrollments (+ revoke) |
| `routes_jobs.py` | 551 | Compose, presort (5-bucket cascade + batch creation), schedule (explicit + selector), reconcile-integrity, close, integrity-summary, print runs (start/complete/abort) |
| `routes_pieces.py` | 464 | Mail pieces + scan events (append-only, 3 refusal reasons), reprints (OCC + net-zero stock), undeliverable returns (+ classify), presort batches (seal/unseal/manifest) |
| `start.sh` | 8 | Guarded `pip install`, `exec python3 app.py` in foreground |

Total 2,943 lines of Python. Storage is process-memory only; nothing is seeded at boot (verified: `GET /bureau/clients` on a fresh process returns `total_count: 0`).

## Endpoint coverage
64/64. Diffed the Flask URL map against every `method`+`path` pair in `SCAFFOLD.yaml`: zero missing, zero extra.

## Smoke test (PORT=18631, killed by its own PID afterwards; port confirmed free)
Full happy path passed 30/30 assertions: client -> deposit -> DR drill -> insert stock -> template + activate -> press line -> facility -> data file -> 3 records -> validate-format -> control-check (ACCEPTED) -> compose -> presort -> schedule -> start -> 9 scans -> complete -> reconcile (MATCHED/VERIFIED) -> seal -> manifest -> close. Numbers cross-checked by hand: postage 3x53=159 estimated, 3x51=153 manifested at 300 bp, variance -6, escrow conservation exact (`committed=153`, `available=5,000,000-153`), billing 81+12=93, insert ledger 500 = 497+0+3.
Second flow exercised the harder branches: paperless suppression (piece 1 SUPPRESSED, electronic count 1), variable-content rule adding a sheet, MIXED_AADC fallback, DUPLICATE_STAGE + UNKNOWN_BARCODE scan refusals (both persisted as events), reconcile -> BREACHED/INTEGRITY_HELD, reprint (barcode `...-000002-R1`, `billable=false`, predecessor VOID, net-zero stock, hold minutes credited, job back to PRINTED), undeliverable return -> classify ADDRESS_UPDATED -> address-feedback batch 1 -> `ERR_NO_PENDING_FEEDBACK` on the repeat. Explicit-mode `selection_score` = 30800.00 matches the 6000/4000 bp formula.

One fix made during smoke: `json_body()` now uses `get_json(force=True)` so a JSON body sent without a `Content-Type` header still parses instead of returning `ERR_VALIDATION`.

## Adjudications on ambiguous PRD wording
1. **§2.10 precedence overrides §3 prose ordering** wherever they disagree — uniqueness (L7) before state gates (L8), so `ERR_DUPLICATE_CODE` precedes `ERR_CLIENT_SUSPENDED`/`ERR_FILE_INVALID_STATE` on statement records, and `ERR_RETURN_DUPLICATE` precedes `ERR_PIECE_NOT_SCANNABLE`. Seal: job-state -> `ERR_BATCH_NOT_OPEN` -> `ERR_STALE_CLIENT_VERSION` -> escrow. Manifest: `ERR_BATCH_NOT_SEALED` -> facility-closed -> SoD -> window -> capacity -> escrow. Schedule: 404s -> job-state -> line-unavailable -> DR -> window-in-past -> capability -> conflict -> capacity.
2. **Scaffold preconditions comparing `X-User-ID` to entity ids are ignored** (§2.1 says identities are opaque); `X-User-ID` is used only for the two segregation-of-duties comparisons (`sealed_by_user_id` at manifest, `composed_by_user_id` at close).
3. **`amend-control-totals` recomputes** the variances against the amended declarations (rejecting the scaffold's "clear to 0"), resets `format_error_count` to 0 and every record's `format_valid` to false, and returns the file to RECEIVED.
4. **`projected_penalty_cents`** is null at composition but reset to **0** (not null) on abort — the PRD states this asymmetry explicitly.
5. **Version bumps** fire only when a field value actually changes, except where the PRD mandates an unconditional bump (validate-format, presort-batch recompute on reprint, PATCH client, PATCH dr-site, drills, classify).
6. **`POST /_clock/set_current_utc`** returns `data: {}` (scaffold says `output: null`, PRD's empty-object rule wins).
7. **`GET .../integrity-summary`** returns the full job object (a superset of the seven named fields) with no version bump.
8. **`amount_cents` and `replication_lag_minutes`** have no declared bound; both enforced `>= 0` with `ERR_VALIDATION`.
9. **Datetime inputs** accept `Z` and `+00:00` only; naive or non-zero-offset instants are `ERR_VALIDATION`.
10. **Enum-valued query filters** are validated against their declared sets (§2.10 level 3), so `?status=NOPE` is 422 rather than an empty page.
11. **Variable-content-rule entries** must carry all four members (`required_insert_code` may be null) — a missing member is a request-shape failure.
12. **Freshly attached records** leave `hygiene_confidence`, `computed_sheet_count` and `computed_insert_codes` null; the PRD enumerates only the three fields it initializes.
13. **Insert consumption at MANIFESTED** = count of pieces carrying the code whose `piece_status` is neither SUPPRESSED nor VOID, which is provably equal to the reserved figure across reprints.

## Step 5: Generate Unit Tests — 2026-09-04T02:35:00.000Z

Test generation for task 2631 is complete.

## Files written

`test_helpers/` (9 files, 3,145 lines): `__init__.py` 77, `api_client.py` 472, `api_errors.py` 154, `assertions.py` 746, `constants.py` 211, `factories.py` 429, `fixtures.py` 957, `test_users.py` 99, `types.py` 482.

`test_suite/` (18 files, 9,361 lines): `conftest.py` 37; queue A `test_01_dual_variant_calc.py` 343, `test_02_combinatorial_formula.py` 382, `test_03_non_linear_state_machine.py` 450, `test_04_transitive_cascade.py` 335, `test_05_priority_pair_validation_conflict.py` 437, `test_06_boundary_precision_check.py` 419, `test_07_cross_entity_state_dependency.py` 472, `test_08_resource_temporal_overlap.py` 420, `test_09_compensating_invariant.py` 529; queue B `test_10_corner_entities.py` 673, `test_11_corner_state_machines.py` 710, `test_12_corner_calculations.py` 1053, `test_13_corner_validations.py` 640, `test_14_corner_endpoints.py` 607, `test_15_corner_errors.py` 752, `test_16_corner_rbac.py` 326, `test_17_corner_cross_cutting.py` 294.

Both directories are at the task root; nothing was created under `workspace/`, and `workspace/implementation/` was never read or touched (only `workspace/PRD.md`). `python3 -m py_compile` passes on all 27 generated .py files; no `__pycache__`/`.bak` residue left behind.

## Tests emitted

142 tests, 89 distinct `Design:` tags, 0 untagged, 0 multi-tagged, 0 tags resolving to a non-existent or stubbed instance.
- Queue A (difficulty §1.8): 24 non-stub instances -> 77 tests.
- Queue B (corner §1.9): 65 non-stub instances -> 65 tests (entities 13, state_machines 11, calculations 13, validations 9, endpoints 6, errors 7, rbac 4, cross_cutting 1, consistency_model 1).

## Coverage audit

Every non-stub instance in both indices was translated — nothing was skipped, weakened, or marked xfail. The 27 `excluded_because:` stubs in the corner index were not translated (by contract); all 27 of their `difficulty_instance` cross-references were verified to resolve to real queue-A instances, so the coverage they name is genuinely carried by queue A.

## Citation compliance

Every one of the 142 docstrings opens with a verbatim, rule-bearing PRD quote (`PRD §x.y: "..."`) and ends with exactly one `Design:` line. An AST-based verifier confirms for all 142: docstring starts with `PRD §`, the quote is closed, the whitespace-normalised quote appears literally in `workspace/PRD.md`, and `Design:` is the last line ("ALL CITATIONS OK"). Note: line-wrapping of citations uses `break_on_hyphens=False` so hyphenated PRD terms stay greppable.

## Adjudications

1. **`X-User-ID` scoping.** PRD §2.1 ("No endpoint scopes its result set or its permission decision to the identity in `X-User-ID`") overrides the scaffold's `complexity_profile` hint; no test asserts identity-scoped result sets.
2. **Empty `capabilities` in design recipes.** Recipes C9, C12, V3, V4, E2, E4, E5, E6, X4, X7, R1, R4 specify `capabilities: []`, which PRD §3.6 forbids (must be a non-empty subset of {DUPLEX, COLOR, INSERT}). Substituted `["DUPLEX"]` with asserted outcomes unchanged; for X5's `PL-X5N`, whose point is *lacking* DUPLEX, substituted `["COLOR"]`.
3. **Consequence of (2) for E6.** With a qualifying capability set the recipe's selection scores become 340.00/339.40 rather than 840.00/839.40 (one surplus capability x 500 penalty), asserted via `a.expected_selection_score(1000, 600, 1)` and `(999, 600, 1)`.

Orchestrator verification: `test_helpers/` and `test_suite/` both confirmed present at the TASK ROOT with no stray copies under `workspace/` (guarding the known misplacement failure mode). 18 files in test_suite/.

## Step 7: Run Tests and Iterate — 2026-09-04T03:04:00.000Z

All 8 parallel rounds green: **142/142 passed** in every round.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each).
- Sweep 1: 10/142 passed in all 8 rounds
- Sweep 2: 141/142 in all 8 rounds
- Sweep 3: 142/142 in all 8 rounds

**Tests deleted:** none. One assertion removed under STEP 1c (partial-coverage split), see below.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `client_payload()` default `client_code` changed `"CL-BASE"` -> `"CLBASE"`. PRD §3.1 restricts `client_code` to "uppercase letters A through Z and the digits 0 through 9, between 3 and 10 characters long inclusive"; the hyphen made every fixture-built client a PRD-correct `ERR_VALIDATION` (422), which cascaded as `Setup step failed` into 131 of 142 tests.
- `test_helpers/fixtures.py` — same fix on the `presorted_job()` pipeline builder's default `client_code` (`"CL-P1"` -> `"CLP1"`).

**Fixes applied to `test_suite/`** (all the same STEP 2 root cause — hyphenated client codes violating PRD §3.1's charset):
- ~75 hyphenated `client_code` literals de-hyphenated across `test_01`...`test_17` (e.g. `"CL-V7"` -> `"CLV7"`), preserving per-test uniqueness. `test_16_corner_rbac.py`'s `"CL-R1-LIAISON"` became `"CLR1LIA"` so it also fits the 10-character ceiling.
- `test_suite/test_05_priority_pair_validation_conflict.py::TestDrReadinessOutranksPressCapacity::test_neither_rejection_reserves_press_capacity` — removed `assert job["projected_penalty_cents"] == 0`. **DEFAULT-VALUE SILENCE / not uniquely derivable:** PRD §3.4 says a composed job begins with `projected_penalty_cents` "unwritten", deliberately contrasted in the very same sentence against `sla_hold_minutes` **0** — so `null` and `0` are both faithful readings for a never-scheduled job (PRD only pins `0` for the *abort* path in §3.6, which this test does not exercise). The test itself was internally inconsistent, reading the identical "unwritten" wording as `None` for `projected_completion_at` one line later. The surrounding assertions (job still `PRESORTED`, `projected_completion_at` null, line ledger at `committed_sheet_count` 0 / `utilization_bp` 0, no print run created) are PRD-verbatim and were kept.

**Fixes applied to `implementation/`:** none. The implementation was correct throughout — notably `calc.py:CLIENT_CODE_PATTERN = r"^[A-Z0-9]{3,10}$"` already matched PRD §3.1 exactly, and its `null`-for-unwritten rendering of `projected_penalty_cents` is a faithful reading of §3.4.

**Note on tooling:** `setsid` forks when the caller is already a process-group leader, so the sweep's outer `bash` returns before `wait` completes. Appended a poll loop on the 8 `results.$i.json` files rather than trusting the wrapper's exit status — the first sweep's exit code 2 was just the trailing `ls` firing early, not a failed run.

Orchestrator verification (guarding the known "clean sweep with no artifacts" failure mode): read all 8 `workspace/implementation/results.$i.json` directly — every file reports `passed`=142, `total`=142.

## Step 8 decision

NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 2 `test_helpers/` fixes and ~76 `test_suite/` edits including one partial-coverage assertion removal, so PRD silences exist at those sites and Step 8 must run. Note that the bulk `client_code` de-hyphenation is a pure fixture bug (PRD §3.1 already pins the charset unambiguously and impl matches it), so Step 8 is expected to make no PRD edit for it; the one genuine PRD-silence candidate is `projected_penalty_cents` on a composed-but-never-scheduled job.

## Step 8: Finalize PRD — 2026-09-04T03:12:00.000Z

`PRD_FINALIZED.md` is written. Only one of the three Step 7 item groups turned out to be a genuine PRD silence; the rest were pure fixture bugs.

**Line/char counts:** PRD.md 479 lines / 111,995 chars -> PRD_FINALIZED.md 479 lines / 112,132 chars. Line delta 0 (0.0%), char delta +137 (+0.12%). One line modified (line 215), not byte-identical.

**Changes**

- §3.4 (composition, job initial field state) — revise — appended a clause pinning that the ten "unwritten" job fields (`sla_completed_at`, `projected_completion_at`, `projected_penalty_cents`, `assessed_penalty_cents`, `composition_charge_cents`, `insert_charge_cents`, `pre_discount_subtotal_cents`, `volume_discount_cents`, `expedite_fee_cents`, `billing_total_cents`) are each present on the job and read as **null** until the step that writes them, and that none starts at 0 — `implementation/routes_jobs.py:153-164`, rendered by `implementation/core.py:254-270`.

**No PRD edit for the client_code items.** PRD §3.1 (line 165) already says `client_code` is "restricted to uppercase letters A through Z and the digits 0 through 9, between 3 and 10 characters long inclusive", which matches `implementation/calc.py:90` (`^[A-Z0-9]{3,10}$`) and `implementation/routes_ref.py:38` exactly. The ~75 test_suite literals and two test_helpers defaults were fixture bugs against an already-determined PRD rule, so patching the PRD would have been out of scope and would have weakened a correct constraint.

**Per-edit pre-edit search log**

Edit 1 — §3.4 "unwritten" clause
- (a) **Subject identified:** the initial/default value of `projected_penalty_cents` on a newly composed job, and more generally the meaning of "unwritten" for all ten fields the same sentence lists — i.e. `null` vs `0`.
- (b) **Impl paths enumerated (read/grepped):**
  - `implementation/routes_jobs.py:137-165` — the composition initializer; confirmed all ten fields set to `None`, alongside `sla_hold_minutes: 0` and the other explicit-zero counters, so the PRD's `0`/unwritten contrast is real.
  - `implementation/core.py:254-270` (`serialize`) — `None` falls through the `else` branch unchanged, so the key is always present and emitted as JSON `null`; nothing coerces it to 0 or drops the key.
  - `implementation/routes_jobs.py:387-388` — the only forward write of `projected_completion_at`/`projected_penalty_cents`, at successful scheduling, after all validation (so a rejected schedule attempt leaves both `null` — this is precisely the Step 7 assertion site).
  - `implementation/routes_jobs.py:547-548` — abort resets `projected_completion_at` to `None` and `projected_penalty_cents` to `0`; checked that the "starts at" phrasing does not contradict this later-write-to-zero, already pinned in §3.6.
  - `implementation/routes_jobs.py:438-443` — closure writes `sla_completed_at`, `assessed_penalty_cents` and the six billing fields; confirmed these are the only other writers of the listed fields.
  - Exhaustive grep for every one of the ten field names across `implementation/*.py` — confirmed no other initializer, presort path, integrity/reconcile path, or reprint path touches them, so no code path is mis-described by "reads as null until the step that writes it".
  - `implementation/calc.py:261` and `implementation/domain.py:213-219` — checked the `sla_hold_minutes` accumulator, since the same PRD sentence pins it at `0`; the edit deliberately excludes it from the null list.
  - Grep for "unwritten" in PRD.md — single occurrence, so no other passage needed the parallel clarification.
- (c) **Wording adjustment made:** kept the original word "unwritten" verbatim and appended rather than replaced, so §3.8's existing "`assessed_penalty_cents`, which is null until closure" stays consistent instead of duplicated. Used "until the step that writes it does so" rather than naming scheduling/closure specifically, so the abort path's later write of `0` (§3.6) and the closure billing writes are not excluded. Scoped the zero-exclusion as "none of them **starts** at 0" rather than "is never 0", which would have falsely contradicted `routes_jobs.py:548`.

Orchestrator verification: `wc` confirms 479 lines / 112,132 chars; `cmp` confirms PRD_FINALIZED.md is not byte-identical to PRD.md; tail confirms it still ends at the completed §5 error catalogue.

## Step 9: Complete PRD — 2026-09-04T03:41:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan, to guard the known failure mode where a single-pass Step 9 silently never scans and leaves `PRD_COMPLETED.md` byte-identical to its source. Each pass edited the same `workspace/PRD_COMPLETED.md`; pass 1 created it from `PRD_FINALIZED.md`.

**Final file state:** `PRD_COMPLETED.md` — 481 lines / 124,781 chars, up from `PRD_FINALIZED.md` at 479 / 112,132 (**+12,649 chars / +11.3%**, +2 lines). 61 edits total across the three passes. 28 `^#` headings intact (§1–§5); tail ends at the completed §5 error catalogue.

### PASS 1 — `app.py`, `core.py`, `calc.py`, `domain.py` (global mechanics + 13 calculations + shared helpers)
479 lines / 115,598 chars (+3,466). **10 ambiguity-pins, 2 mismatch-revisions (12 edits).**
- §2.1 — insert — ambiguity — an auth header present but carrying an empty string counts as absent (`ERR_MISSING_AUTH_HEADERS`) — core.py:300
- §2.3 (ordering) — insert — ambiguity — ties on every declared ordering key are broken by server insertion sequence, and the same tiebreak governs the internal processing orders the PRD pins — core.py:494, domain.py:72,80
- §2.3 (filters) — insert — ambiguity — enum-valued filters validated against the values the field can hold on that resource, out-of-set is `ERR_VALIDATION`; `accepted` accepts true/false/1/0; identifier filters match literally (no not-found); undefined query params ignored — core.py:464-484
- §2.4 — insert — ambiguity — sub-millisecond precision truncated in rendering, not rounded, while the stored instant keeps full precision for comparisons — core.py:48-54, 62-80
- §2.6 — insert — **mismatch** — the two 2-decimal fields are emitted as plain JSON numbers, so trailing zeros are lost (0.90 -> `0.9`, 1.00 -> `1.0`), contradicting a literal reading of "exactly two decimal places" — core.py:264-265
- §2.9 — revise — ambiguity — `utilization_bp` quotient rounded half up to a whole basis point — calc.py:231
- §2.10 item 3 — insert — ambiguity — omitted/empty body = empty JSON object; unparseable or non-object body = `ERR_VALIDATION`; `Content-Type` not consulted; explicit `null` == omitted; integer fields reject booleans and fractional numbers; datetimes accept `Z` or zero offset, 1-9 fractional digits, space separator, and reject non-zero offset / naive; `limit`/`offset` must be integer-formatted — core.py:314-325, 328-330, 359-369, 402-414, 443-461
- §3.7 — insert — ambiguity — defines `void_piece_count` (pieces in `VOID`) and `reprint_piece_count` (pieces with non-null `reprint_of_piece_id`) — domain.py:176-177
- §3.7 — revise — ambiguity — integrity-hold elapsed minutes rounded half up to a whole minute, never contributing a negative figure — domain.py:216-219
- §3.8 — insert — ambiguity — both penalty variants measure lateness as an exact span keeping fractional minutes (matters because the /60 step rounds up) — core.py:103-105, calc.py:242,254,261
- §3.9 — revise — **mismatch** — a statement record reached twice in one feedback release is version-bumped once, not once per return — domain.py:128-137
- §5 preamble — insert — ambiguity — out-of-catalogue pre-routing failures: `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — app.py:46-62

Verified already-pinned (not re-litigated by later passes): the full §5 error catalogue vs `core.py` ERROR_STATUS with zero name/status divergence; every one of the 13 calculation formulas (format predicate, `control_total_variance_bp`, hygiene weights/thresholds, `compose_sheets`, barcode minting, base-rate table + 3-sheet/3-cent surcharge, per-piece net postage, press requirement set, `line_score` 6000/4000/-500 at 2-dp half-up, `run_minutes_for` max(60, ceil), `window_conflicts` both-sided closed buffer, severity 10000/15000, penalty tail with cap last, discount tiers 400/230/200, 8-step invoice, `dr_readiness` step function with exclusive boundaries); envelope/meta/`has_more` arithmetic and the single-reads-omit-pagination rule.

### PASS 2 — `routes_ref.py`, `routes_intake.py`
481 lines / 120,804 chars (+5,206, +2 lines). **16 ambiguity-pins, 2 mismatch-revisions (18 edits).** Re-verified the §5 catalogue programmatically against `core.py`: 54 entries both sides, zero divergence (pass 1's "55" was an off-by-one in its own report, not a defect in the file).
- §2.3 — revise — ambiguity — identifier-valued *and* the free-text `jurisdiction_code` filter compared literally with no validation of their own — routes_ref.py:400, core.py:464
- §2.4 — revise — ambiguity — `current_utc` required; the clock call answers 200 with an empty `data` object, not a resource — routes_ref.py:20-26
- §2.5 — revise — **mismatch** — only composition raises `ERR_CLIENT_MISMATCH`; the address-feedback release enforces ownership by scoping, never by rejection — routes_ref.py:161-169 vs routes_jobs.py:31
- §2.11 — revise — ambiguity — `site_code` required, >=1 char, no upper bound; `replication_lag_minutes` required, non-negative, unbounded above; `drill_count` starts 0 — routes_ref.py:510-523
- §2.11 — insert — ambiguity — drills (`result` required, `last_drill_at`/`last_drill_result` overwritten, `drill_count`+1 on `FAIL` too, `version`+1) and the lag PATCH (`replication_lag_minutes` its only field and required there; an unchanged value still bumps `version`; reads recompute without bumping) — routes_ref.py:534-555, 499-503
- §3.1 — revise — ambiguity — every PATCH-client field optional, and the amendment bumps `version`/`updated_at` **unconditionally** — an empty or value-restating PATCH is accepted and still bumps — routes_ref.py:88-115
- §3.1 — revise — ambiguity — deposit: `amount_cents` required and >=0 (0 accepted, still bumps `version`); `reference` string-validated but never persisted; answers with the client — routes_ref.py:118-130
- §3.1 — revise — ambiguity — `confirm_pending_account_refs` is a required string array that may be empty (epoch still advances) or repeat entries — routes_ref.py:137
- §3.1 — revise — ambiguity — the sync run answers with the updated client, not the confirmed enrollments — routes_ref.py:151
- §3.1 — insert — ambiguity — enrollment reinstatement keeps `id`/`created_at` and answers **HTTP 201** — routes_intake.py:230-241
- §3.2 — revise — ambiguity — `description`/`jurisdiction_code` required but wholly unconstrained (empty string accepted); `effective_from` required; the two endpoints never compared, so an inverted window is accepted and simply never effective — routes_ref.py:360-364
- §3.2 — revise — ambiguity — all four rule members must be *physically present* (so `required_insert_code` must be spelled `null`, unlike top-level fields where null == omitted); `rule_code` non-empty and unbounded; extra members ignored and each entry persisted as exactly those four; either array as `null` reads as its empty default; both arrays keep supplied order — routes_ref.py:232-267, 293, 310-311
- §3.3 — revise — ambiguity — `statement_amount_cents` required but unbounded (negative accepted, caught later by the predicate); the four address strings required but wholly unconstrained (empty accepted) — routes_intake.py:170-175
- §3.3 — revise — ambiguity — fresh record also has `address_update_pending` false and `hygiene_confidence`/`computed_sheet_count`/`computed_insert_codes` reading **null** — routes_intake.py:198-204
- §3.3 — insert — ambiguity — a record's `version` bumps on the format mark only when the mark actually flips — routes_intake.py:70
- §3.3 — revise — ambiguity — an amendment supplying neither figure is `ERR_AMENDMENT_NO_CHANGE`; the `format_valid` reset bumps a record only where the mark was not already false — routes_intake.py:113-132
- §3.6 — revise — ambiguity — `capabilities` persisted/echoed in supplied order — routes_ref.py:433
- §3.8 — revise — ambiguity — `tray_capacity_per_window` and both discount fields are required, not defaulted — routes_ref.py:471-473
- §3.9 — revise — ambiguity + **mismatch** — `note` string-validated but never persisted; and the release is scoped, not validated: a foreign-client return is silently left alone rather than raising `ERR_CLIENT_MISMATCH`; answers with the client — routes_ref.py:154-186

### PASS 3 — `routes_jobs.py`, `routes_pieces.py`
481 lines / 124,781 chars (+3,977). **9 ambiguity-pins, 10 mismatch-revisions (19 edits, 9 mismatch subjects — §3.9 needed two paragraph edits).**
- §2.5 — revise — mismatch — deleted the unenforceable "scanned piece must belong to the job it is claimed against"; replaced with the fact that no piece-scoped operation names a job at all, the job being reached from the piece's own `composition_job_id` (and a return's only route via `mail_piece_id`) — routes_pieces.py:89-99, 140-149, 216-226
- §3.4 — insert — ambiguity — compose resolves both body refs before any state gate, `data_file_id` first, so a doubly-bogus request answers `ERR_DATA_FILE_NOT_FOUND` — routes_jobs.py:28-29
- §3.4 — revise — mismatch — "the **whole** composition is refused" on `ERR_INSERT_STOCK_INSUFFICIENT` was false: no job/piece/stock movement persists and the file stays `ACCEPTED`, but the hygiene marks already written onto every statement record (and their `version` increments) stand — routes_jobs.py:84 vs 122-125
- §3.4 — insert — ambiguity — "billable pieces only" now states that at composition this means *every* piece including `SUPPRESSED` ones, only a reprint replacement being unbillable — routes_jobs.py:105, 135, 148-151
- §3.5 — insert — ambiguity — a candidate piece's `presort_bucket` and `presort_batch_id` are written in one mutation, so its `version` moves by exactly 1 across the whole presort — routes_jobs.py:291-295
- §3.6 — revise — mismatch — "Before anything else about the press floor is considered, DR posture is checked" contradicted §2.10: a named line in `MAINTENANCE` is refused first; also pinned that a readiness-requiring client with **no** DR site registered gets `ERR_DR_SITE_NOT_READY`, not a not-found — routes_jobs.py:313-320
- §3.6 — revise — mismatch — "Neither figure is ever recomputed once written" was false for `projected_completion_at`/`projected_penalty_cents`: an abort clears them and a re-schedule rewrites them — routes_jobs.py:387-388 vs 547-548
- §3.6 — revise — mismatch — run start does not test that the job is `SCHEDULED`; reworded as structurally guaranteed, with `ERR_PRESS_LINE_UNAVAILABLE` reported after the run-status gate — routes_jobs.py:482-486
- §3.6 — insert — ambiguity — `abort_reason` is a **required** field despite `NONE` being a member of its set — routes_jobs.py:525
- §3.7 — revise — mismatch — `RECONCILED` is not absolutely terminal: a duplicate read on a reconciled piece of an `INTEGRITY_HELD` job drives it to `DUPLICATE_SCAN` — routes_pieces.py:133-135
- §3.7 — insert — ambiguity — `scanned_barcode` and `device_code` are required strings with no length/format bound, empty string accepted — routes_pieces.py:94-95
- §3.7 — insert — ambiguity — the `DUPLICATE_SCAN` write is unconditional: a repeat duplicate at the same stage bumps `version` again with no value change — routes_pieces.py:133-135
- §3.7 — revise — ambiguity — reconciliation *relies on* rather than tests the accountable/expected/actual invariant; no error id exists for it — routes_jobs.py:394-424
- §3.7 — insert — ambiguity — integrity-summary answers with the **full job resource**, the seven named fields being what it exists to surface — routes_jobs.py:210
- §3.7 — insert — ambiguity — `reprint_reason` is validated as a string, never persisted, absent from every response — routes_pieces.py:145
- §3.7 — revise — ambiguity — the reprint's `ERR_INSERT_STOCK_INSUFFICIENT` guard can never fire, because the voided copies return before the replacement reserves — routes_pieces.py:160-163
- §3.9 — insert — ambiguity — `corrected_address_line1`/`corrected_postal_code` carry no length or format constraint; an empty string counts as supplied and is persisted as supplied — routes_pieces.py:253-254, 258-262
- §3.9 (address-updated branch) — revise — mismatch — the client counter increments **once per classified return**, not per newly-flagged record; a second return against the same record's reprint replacement raises it again and re-bumps the record — routes_pieces.py:283-290
- §3.9 (unresolved branch) — revise — mismatch — same per-classification basis stated for the mirror branch — routes_pieces.py:283-290

**Two cross-pass hand-offs, both resolved in pass 3:**
1. §2.5's "the scanned piece must belong to the job it is claimed against" — **confirmed unenforceable**: nothing in `routes_pieces.py` or `routes_jobs.py` checks piece-to-job ownership, and the three piece-scoped operations never accept a job reference; the job is always derived from `piece["composition_job_id"]`. Sentence rewritten to describe what the implementation actually does.
2. `pending_address_feedback_count` — **confirmed and pinned**: `routes_pieces.py:288-290` increments and touches the client on *every* classify, unguarded. Reachable duplicate path verified (return on original -> classify -> reprint -> return on replacement -> classify raises the count twice and bumps the record twice, though `address_update_pending` was already true). Both §3.9 branch paragraphs now state the per-classification basis and drop the "Because the record's flag has flipped" causality.

**Pass 3 closing statement:** every endpoint, precondition, rejection order, default, cascade, counter update, ledger movement, ordering rule and version-bump behaviour in `routes_jobs.py` and `routes_pieces.py` traces to a PRD sentence that admits only the implemented reading. Rejection orders traced all match §2.10; no residual silence or mismatch remains in that partition.

Orchestrator verification: `wc` confirms 481 lines / 124,781 chars; `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran — the known Step 9 failure mode); heading scan shows all five top-level sections present in order and the file ends at the completed §5 catalogue; difficulty-instruction leak grep returns nothing. Step 9 touched documentation only — no `implementation/` change — so the Step 7 sweep evidence (8/8 rounds at 142/142) remains valid and the `results.{1..8}.json` files are retained in `workspace/implementation/`.

## Pipeline complete

All nine steps done. Final artifact set present: SCAFFOLD.yaml + both design indices, test_helpers/ (9 files) + test_suite/ (18 files, 142 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, and results.{1..8}.json all green.
