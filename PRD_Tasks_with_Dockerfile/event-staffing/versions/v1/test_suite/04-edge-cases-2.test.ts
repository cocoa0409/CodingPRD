import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload, StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole,
    ApiErrorId,
    createUnixTimestamp,
    addHours,
    createAndConfirmShift,
    createAndActivateContract,
    setupBasicContract,
} from '../../../test-helpers';

describe('Phase 4: Edge Cases', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);

    describe('Payroll Calculation and Ordering', () => {
        describe('P4-PAYROLL-01.1: Payroll applies overtime chronologically', () => {
            it('should calculate overtime based on chronological shift order', async () => {
                const contractRes = await apiClient.createContract(
                    createContractPayload({ total_budget: 10000.00 }),
                    coordinatorHeaders
                );
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);

                await apiClient.activateContract(contract.id, coordinatorHeaders);

                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 10.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const shiftAStart = createUnixTimestamp(24);
                const shiftAEnd = addHours(shiftAStart, 30);
                const shiftARes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift A',
                        start_time: shiftAStart,
                        end_time: shiftAEnd,
                    }),
                    coordinatorHeaders
                );
                const shiftA = handleApiResponse<Shift>(shiftARes, 201);

                const shiftBStart = addHours(shiftAEnd, 8);
                const shiftBEnd = addHours(shiftBStart, 15);
                const shiftBRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift B',
                        start_time: shiftBStart,
                        end_time: shiftBEnd,
                    }),
                    coordinatorHeaders
                );
                const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

                const shiftCStart = addHours(shiftBEnd, 8);
                const shiftCEnd = addHours(shiftCStart, 5);
                const shiftCRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift C',
                        start_time: shiftCStart,
                        end_time: shiftCEnd,
                    }),
                    coordinatorHeaders
                );
                const shiftC = handleApiResponse<Shift>(shiftCRes, 201);

                const assignARes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shiftA.id, staff.id),
                    accountManagerHeaders
                );
                const assignA = handleApiResponse<Assignment>(assignARes, 201);
                await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignA.id, coordinatorHeaders);

                const assignBRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shiftB.id, staff.id),
                    accountManagerHeaders
                );
                const assignB = handleApiResponse<Assignment>(assignBRes, 201);
                await apiClient.acceptAssignment(contract.id, assignB.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignB.id, coordinatorHeaders);

                const assignCRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shiftC.id, staff.id),
                    accountManagerHeaders
                );
                const assignC = handleApiResponse<Assignment>(assignCRes, 201);
                await apiClient.acceptAssignment(contract.id, assignC.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignC.id, coordinatorHeaders);

                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                const finalARes = await apiClient.getAssignment(contract.id, assignA.id, coordinatorHeaders);
                const finalA = handleApiResponse<Assignment>(finalARes, 200);
                expect(finalA.final_payout).toBeCloseTo(300.00);

                const finalBRes = await apiClient.getAssignment(contract.id, assignB.id, coordinatorHeaders);
                const finalB = handleApiResponse<Assignment>(finalBRes, 200);
                expect(finalB.final_payout).toBeCloseTo(175.00);

                const finalCRes = await apiClient.getAssignment(contract.id, assignC.id, coordinatorHeaders);
                const finalC = handleApiResponse<Assignment>(finalCRes, 200);
                expect(finalC.final_payout).toBeCloseTo(75.00);
            });
        });

    });

    describe('Complex State Interactions and Cascades', () => {
        describe('P4-CASCADE-01.1: Cancelling assignment downgrades event and prevents ready', () => {
            it('should downgrade READY event when assignment cancelled and prevent re-marking', async () => {
                const contractRes = await apiClient.createContract(
                    createContractPayload({ total_budget: 5000.00 }),
                    coordinatorHeaders
                );
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);

                await apiClient.activateContract(contract.id, coordinatorHeaders);

                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                const readyRes = await apiClient.updateEventStatus(
                    contract.id,
                    event.id,
                    { status: EventStatus.READY_FOR_EXECUTION },
                    coordinatorHeaders
                );
                const readyEvent = handleApiResponse<Event>(readyRes, 200);
                expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

                await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                const eventCheckRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
                const downgradedEvent = handleApiResponse<Event>(eventCheckRes, 200);
                expect(downgradedEvent.status).toBe(EventStatus.PLANNING);

                const shiftCheckRes = await apiClient.getShift(
                    contract.id,
                    event.id,
                    shift.id,
                    coordinatorHeaders
                );
                const reopenedShift = handleApiResponse<Shift>(shiftCheckRes, 200);
                expect(reopenedShift.status).toBe(ShiftStatus.OPEN);

                const retryReadyRes = await apiClient.updateEventStatus(
                    contract.id,
                    event.id,
                    { status: EventStatus.READY_FOR_EXECUTION },
                    coordinatorHeaders
                );

                validateErrorEnvelope(retryReadyRes, {
                    expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED
                });
            });
        });

        describe('P4-CASCADE-01.2: Event cancellation cascades and reverts ledgers', () => {
            it('should cascade cancellation to all assignments and revert ledger entries', async () => {
                const contractRes = await apiClient.createContract(
                    createContractPayload({ total_budget: 10000.00 }),
                    coordinatorHeaders
                );
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);

                await apiClient.activateContract(contract.id, coordinatorHeaders);

                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffARes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({
                        first_name: 'Staff',
                        last_name: 'A',
                        base_pay_rate_per_hour: 20.00
                    }),
                    coordinatorHeaders
                );
                const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

                const setupEventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload({ name: 'Setup Event' }),
                    coordinatorHeaders
                );
                const setupEvent = handleApiResponse<Event>(setupEventRes, 201);

                const setupShiftRes = await apiClient.createShift(
                    contract.id,
                    setupEvent.id,
                    createShiftPayload({
                        start_time: createUnixTimestamp(24),
                        end_time: addHours(createUnixTimestamp(24), 40),
                    }),
                    coordinatorHeaders
                );
                const setupShift = handleApiResponse<Shift>(setupShiftRes, 201);

                const setupAssignRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(setupShift.id, staffA.id),
                    accountManagerHeaders
                );
                const setupAssign = handleApiResponse<Assignment>(setupAssignRes, 201);
                await apiClient.acceptAssignment(contract.id, setupAssign.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, setupAssign.id, coordinatorHeaders);

                for (let i = 0; i < 2; i++) {
                    const otherStaffRes = await apiClient.createStaffProfile(
                        contract.id,
                        createStaffProfilePayload({
                            first_name: `Other${i}`,
                            last_name: 'Staff',
                            base_pay_rate_per_hour: 20.00
                        }),
                        coordinatorHeaders
                    );
                    const otherStaff = handleApiResponse<StaffProfile>(otherStaffRes, 201);

                    const otherBaseStart = createUnixTimestamp(100 + i * 100);
                    const otherBaseEnd = addHours(otherBaseStart, 40);
                    const otherBaseShiftRes = await apiClient.createShift(
                        contract.id,
                        setupEvent.id,
                        createShiftPayload({
                            start_time: otherBaseStart,
                            end_time: otherBaseEnd,
                        }),
                        coordinatorHeaders
                    );
                    const otherBaseShift = handleApiResponse<Shift>(otherBaseShiftRes, 201);

                    const otherBaseAssignRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(otherBaseShift.id, otherStaff.id),
                        accountManagerHeaders
                    );
                    const otherBaseAssign = handleApiResponse<Assignment>(otherBaseAssignRes, 201);
                    await apiClient.acceptAssignment(contract.id, otherBaseAssign.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, otherBaseAssign.id, coordinatorHeaders);

                    const otStart = createUnixTimestamp(200 + i * 100);
                    const otEnd = addHours(createUnixTimestamp(200 + i * 100), 5);
                    const otShiftRes = await apiClient.createShift(
                        contract.id,
                        setupEvent.id,
                        createShiftPayload({
                            start_time: otStart,
                            end_time: otEnd,
                        }),
                        coordinatorHeaders
                    );
                    const otShift = handleApiResponse<Shift>(otShiftRes, 201);

                    const otAssignRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(otShift.id, otherStaff.id),
                        accountManagerHeaders
                    );
                    const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
                    await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
                }

                const beforeCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const beforeContract = handleApiResponse<StaffingContract>(beforeCheckRes, 200);
                const baseRiskScore = beforeContract.compliance_risk_score;
                const baseBudgetBalance = beforeContract.budget_balance;

                const shift1Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift 1',
                        start_time: createUnixTimestamp(300),
                        end_time: addHours(createUnixTimestamp(300), 2),
                    }),
                    coordinatorHeaders
                );
                const shift1 = handleApiResponse<Shift>(shift1Res, 201);

                const assign1Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift1.id, staffA.id),
                    accountManagerHeaders
                );
                const assign1 = handleApiResponse<Assignment>(assign1Res, 201);

                const shift2Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift 2',
                        start_time: createUnixTimestamp(320),
                        end_time: addHours(createUnixTimestamp(320), 2),
                    }),
                    coordinatorHeaders
                );
                const shift2 = handleApiResponse<Shift>(shift2Res, 201);

                const assign2Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift2.id, staffA.id, { override_risk_check: true }),
                    accountManagerHeaders
                );
                const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
                await apiClient.acceptAssignment(contract.id, assign2.id, staffMemberHeaders);

                const intermediateCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const intermediateContract = handleApiResponse<StaffingContract>(intermediateCheckRes, 200);
                const assign1Cost = assign1.provisional_cost;
                const assign2Cost = assign2.provisional_cost;

                expect(intermediateContract.compliance_risk_score).toBe(baseRiskScore + 20);
                expect(intermediateContract.budget_balance).toBeCloseTo(baseBudgetBalance - assign1Cost - assign2Cost);

                const cancelRes = await apiClient.updateEventStatus(
                    contract.id,
                    event.id,
                    { status: EventStatus.CANCELLED },
                    coordinatorHeaders
                );
                handleApiResponse<Event>(cancelRes, 200);

                const finalAssign1Res = await apiClient.getAssignment(contract.id, assign1.id, coordinatorHeaders);
                const finalAssign1 = handleApiResponse<Assignment>(finalAssign1Res, 200);
                expect(finalAssign1.status).toBe(AssignmentStatus.CANCELLED);

                const finalAssign2Res = await apiClient.getAssignment(contract.id, assign2.id, coordinatorHeaders);
                const finalAssign2 = handleApiResponse<Assignment>(finalAssign2Res, 200);
                expect(finalAssign2.status).toBe(AssignmentStatus.CANCELLED);

                const finalContractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const finalContract = handleApiResponse<StaffingContract>(finalContractCheckRes, 200);
                expect(finalContract.compliance_risk_score).toBe(baseRiskScore);
                expect(finalContract.budget_balance).toBeCloseTo(baseBudgetBalance);
            });
        });
    });

    describe('P4-COVERAGE-01: Rest Period and Ledger on Decline', () => {
        it('should fail to create an assignment that violates the rest period', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(2000.00);

            const shift1Start = createUnixTimestamp(24);
            const shift1End = addHours(shift1Start, 8);
            const shift1 = await createAndConfirmShift(contractId, eventId, staffId, { start_time: shift1Start, end_time: shift1End });

            const shift2Start = addHours(shift1End, 7);
            const shift2End = addHours(shift2Start, 8);
            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({ start_time: shift2Start, end_time: shift2End }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assignmentRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );

            validateErrorEnvelope(assignmentRes, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION
            });
        });

        it('should correctly decrement budget and risk score when declining an OT assignment', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(5000.00);

            const baseShiftStart = createUnixTimestamp(24);
            const baseShiftEnd = addHours(baseShiftStart, 40);
            await createAndConfirmShift(contractId, eventId, staffId, { start_time: baseShiftStart, end_time: baseShiftEnd });

            const otShiftStart = createUnixTimestamp(72);
            const otShiftEnd = addHours(otShiftStart, 5);
            const otShiftRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({ start_time: otShiftStart, end_time: otShiftEnd }),
                coordinatorHeaders
            );
            const otShift = handleApiResponse<Shift>(otShiftRes, 201);

            const assignmentRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(otShift.id, staffId),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

            const afterProposalRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const afterProposalContract = handleApiResponse<StaffingContract>(afterProposalRes, 200);
            const budgetAfter = afterProposalContract.budget_balance;
            const riskAfter = afterProposalContract.compliance_risk_score;
            expect(riskAfter).toBe(5);

            await apiClient.declineAssignment(contractId, assignment.id, staffMemberHeaders);

            const finalContractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);

            const staffRes = await apiClient.getStaffProfile(contractId, staffId, coordinatorHeaders);
            const staff = handleApiResponse<StaffProfile>(staffRes, 200);
            const expectedBalance = 5000.00 - (40 * staff.base_pay_rate_per_hour);

            expect(finalContract.budget_balance).toBeCloseTo(expectedBalance);
            expect(finalContract.compliance_risk_score).toBe(0);
        });
    });

    describe('P4-COVERAGE-02: Derived Values and Boundary Checks', () => {
        it('should correctly calculate and store the derived shift duration', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(1000.00);

            const shiftStart = createUnixTimestamp(24);
            const shiftEnd = shiftStart + (8.5 * 3600);

            const shiftRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({ start_time: shiftStart, end_time: shiftEnd }),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            expect(shift.duration_hours).toBeCloseTo(8.5);

            const getShiftRes = await apiClient.getShift(contractId, eventId, shift.id, coordinatorHeaders);
            const retrievedShift = handleApiResponse<Shift>(getShiftRes, 200);
            expect(retrievedShift.duration_hours).toBeCloseTo(8.5);
        });

        it('should succeed with an 8-hour rest period and fail with one second less', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(2000.00);

            const shift1Start = createUnixTimestamp(24);
            const shift1End = addHours(shift1Start, 8);
            await createAndConfirmShift(contractId, eventId, staffId, { start_time: shift1Start, end_time: shift1End });

            const shift2Start = shift1End + (8 * 3600);
            const shift2End = addHours(shift2Start, 4);
            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({ role_name: "8-hour-rest", start_time: shift2Start, end_time: shift2End }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);
            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );
            handleApiResponse<Assignment>(assignment2Res, 201);

            const shift3Start = shift1End + (8 * 3600) - 1;
            const shift3End = addHours(shift3Start, 4);
            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({ role_name: "less-than-8-hour-rest", start_time: shift3Start, end_time: shift3End }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);
            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift3.id, staffId),
                accountManagerHeaders
            );
            validateErrorEnvelope(assignment3Res, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION
            });
        });
    });

    describe('P4-COVERAGE-04: Rest Period Validation on Confirmation', () => {
        it('should fail to confirm an assignment if it violates rest period with another committed shift', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(5000.00);

            const shift1Start = createUnixTimestamp(8);
            const shift1End = addHours(shift1Start, 8);
            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: shift1Start, end_time: shift1End }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Start = addHours(shift1End, 4);
            const shift2End = addHours(shift2Start, 8);
            const shift2Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: shift2Start, end_time: shift2End }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assign1Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);
            const assign1 = handleApiResponse<Assignment>(assign1Res, 201);

            const assign2Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staffId), accountManagerHeaders);
            validateErrorEnvelope(assign2Res, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION,
            });

            await apiClient.acceptAssignment(contractId, assign1.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contractId, assign1.id, coordinatorHeaders);
        });
    });

    describe('Resource Not Found and State Integrity', () => {
        describe('P4-STATE-01.1: Confirming assignment fails if shift state is wrong', () => {
            it('should fail to confirm an assignment if the shift is not PENDING_CONFIRMATION', async () => {
                const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);
                await apiClient.activateContract(contract.id, coordinatorHeaders);

                const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);

                await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                const staff2Res = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }), coordinatorHeaders);
                const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);
                const newAssignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff2.id),
                    accountManagerHeaders
                );
                const newAssignment = handleApiResponse<Assignment>(newAssignmentRes, 201);

                await apiClient.declineAssignment(contract.id, newAssignment.id, staffMemberHeaders);

                const shiftCheckRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
                const openShift = handleApiResponse<Shift>(shiftCheckRes, 200);
                expect(openShift.status).toBe(ShiftStatus.OPEN);

                const confirmRes = await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                validateErrorEnvelope(confirmRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED
                });
            });
        });

        describe('P4-STATE-01.2: Operations on a CLOSED contract are rejected', () => {
            let closedContract: StaffingContract;
            let eventInClosedContract: Event;

            beforeEach(async () => {
                const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);
                await apiClient.activateContract(contract.id, coordinatorHeaders);
                const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
                eventInClosedContract = handleApiResponse<Event>(eventRes, 201);

                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);
                closedContract = handleApiResponse<StaffingContract>(finalizeRes, 200);
                expect(closedContract.status).toBe(ContractStatus.CLOSED);
            });

            it('should fail to create an event in a CLOSED contract', async () => {
                const eventRes = await apiClient.createEvent(
                    closedContract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                validateErrorEnvelope(eventRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                });
            });

            it('should fail to create a shift in a CLOSED contract', async () => {
                const shiftRes = await apiClient.createShift(
                    closedContract.id,
                    eventInClosedContract.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                validateErrorEnvelope(shiftRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                });
            });
        });
    });

    describe('P4-RISK-03.1: Budget check has precedence over risk check', () => {
        it('should return budget error when both risk threshold and budget are exceeded', async () => {
            const contract = await apiClient.createContract(createContractPayload({ total_budget: 3319.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 201));
            await apiClient.activateContract(contract.id, coordinatorHeaders);
            const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));

            for (let i = 0; i < 3; i++) {
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: `OTStaff${i}`, base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const otShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000 + (i * 150000), end_time: 1700000000 + (i * 150000) + 147600 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const otAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, otAssign.id, buildUserHeaders(`staff-${i}`, UserRole.StaffMember));
                await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
            }

            const mainStaff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Main', base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

            const baseShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700500000, end_time: 1700644000 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
            const baseAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(baseShift.id, mainStaff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
            await apiClient.acceptAssignment(contract.id, baseAssign.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, baseAssign.id, coordinatorHeaders);

            const finalOtShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700700000, end_time: 1700703600 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

            const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(finalOtShift.id, mainStaff.id), accountManagerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        });
    });

    describe('P4-RISK-04.1: Real-time compliance risk score synchronization', () => {
        it('should have the contract risk score reflect ledger changes immediately', async () => {
            const contract = await createAndActivateContract(20000.00);
            const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
            const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 10.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

            const baseShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700144000 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
            const baseAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(baseShift.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
            await apiClient.acceptAssignment(contract.id, baseAssign.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, baseAssign.id, coordinatorHeaders);

            const contractState0 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState0.compliance_risk_score).toBe(0);

            const otShift1 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700200000, end_time: 1700203600 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
            const otAssign1 = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift1.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
            const contractState1 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState1.compliance_risk_score).toBe(5);

            await apiClient.declineAssignment(contract.id, otAssign1.id, staffMemberHeaders);
            const contractState2 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState2.compliance_risk_score).toBe(0);

            for (let i = 0; i < 3; i++) {
                const start = 1700300000 + (i * 86400);
                const end = start + 3600;
                const otShift = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ start_time: start, end_time: end }),
                    coordinatorHeaders
                ).then(r => handleApiResponse<Shift>(r, 201));
                await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(otShift.id, staff.id),
                    accountManagerHeaders
                ).then(r => handleApiResponse<Assignment>(r, 201));
            }
            const contractState3 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState3.compliance_risk_score).toBe(15);

            const otShiftFinalStart = 1700300000 + (3 * 86400);
            const otShiftFinal = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ start_time: otShiftFinalStart, end_time: otShiftFinalStart + 3600 }),
                coordinatorHeaders
            ).then(r => handleApiResponse<Shift>(r, 201));
            const otAssignFinal = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShiftFinal.id, staff.id, { override_risk_check: true }), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
            const contractState4 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState4.compliance_risk_score).toBe(30);

            await apiClient.cancelAssignment(contract.id, otAssignFinal.id, coordinatorHeaders);
            const contractState5 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
            expect(contractState5.compliance_risk_score).toBe(15);
        });
    });
});
