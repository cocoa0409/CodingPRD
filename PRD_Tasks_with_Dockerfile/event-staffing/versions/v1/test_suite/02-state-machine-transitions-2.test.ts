import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope, assertAssignment,
    createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole, ApiErrorId
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('Assignment State Machine', () => {
        let testContract: StaffingContract;
        let testEvent: Event;
        let testShift: Shift;
        let testStaff: StaffProfile;

        beforeEach(async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Assignment Test Contract' }),
                coordinatorHeaders
            );
            const contract = getSuccessData<StaffingContract>(contractRes);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            testContract = handleApiResponse<StaffingContract>(activateRes, 200);

            const eventRes = await apiClient.createEvent(
                testContract.id,
                createEventPayload({ name: 'Assignment Test Event' }),
                coordinatorHeaders
            );
            testEvent = getSuccessData<Event>(eventRes);

            const shiftRes = await apiClient.createShift(
                testContract.id,
                testEvent.id,
                createShiftPayload({ role_name: 'Test Role' }),
                coordinatorHeaders
            );
            testShift = getSuccessData<Shift>(shiftRes);

            const staffRes = await apiClient.createStaffProfile(
                testContract.id,
                createStaffProfilePayload({ first_name: 'Test', last_name: 'Staff' }),
                coordinatorHeaders
            );
            testStaff = getSuccessData<StaffProfile>(staffRes);
        });

        describe('Transition: accept_assignment (PROPOSED -> ACCEPTED)', () => {
            describe('P2-ASSIGN-01.1: PROPOSED assignment successfully transitions to ACCEPTED', () => {
                it('should transition assignment from PROPOSED to ACCEPTED', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);
                    expect(assignment.status).toBe(AssignmentStatus.PROPOSED);

                    const acceptRes = await apiClient.acceptAssignment(
                        testContract.id,
                        assignment.id,
                        staffMemberHeaders
                    );
                    const acceptedAssignment = handleApiResponse<Assignment>(acceptRes, 200);

                    assertAssignment(acceptedAssignment);
                    expect(acceptedAssignment.status).toBe(AssignmentStatus.ACCEPTED);

                    const getRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
                    expect(retrievedAssignment.status).toBe(AssignmentStatus.ACCEPTED);
                });
            });

            describe('P2-ASSIGN-01.2: Accepting CONFIRMED assignment fails', () => {
                it('should fail when trying to accept an already confirmed assignment', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const confirmedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const confirmedAssignment = handleApiResponse<Assignment>(confirmedRes, 200);
                    expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);

                    const acceptRes = await apiClient.acceptAssignment(
                        testContract.id,
                        assignment.id,
                        staffMemberHeaders
                    );

                    validateErrorEnvelope(acceptRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED
                    });

                    const finalRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
                    expect(finalAssignment.status).toBe(AssignmentStatus.CONFIRMED);
                });
            });
        });

        describe('Transition: decline_assignment (PROPOSED -> DECLINED)', () => {
            describe('P2-ASSIGN-02.1: PROPOSED assignment successfully transitions to DECLINED', () => {
                it('should transition assignment from PROPOSED to DECLINED', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);
                    expect(assignment.status).toBe(AssignmentStatus.PROPOSED);

                    const declineRes = await apiClient.declineAssignment(
                        testContract.id,
                        assignment.id,
                        staffMemberHeaders
                    );
                    const declinedAssignment = handleApiResponse<Assignment>(declineRes, 200);

                    assertAssignment(declinedAssignment);
                    expect(declinedAssignment.status).toBe(AssignmentStatus.DECLINED);

                    const getRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
                    expect(retrievedAssignment.status).toBe(AssignmentStatus.DECLINED);
                });
            });

            describe('P2-ASSIGN-02.2: Declining ACCEPTED assignment fails', () => {
                it('should fail when trying to decline an already accepted assignment', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);

                    const acceptedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const acceptedAssignment = handleApiResponse<Assignment>(acceptedRes, 200);
                    expect(acceptedAssignment.status).toBe(AssignmentStatus.ACCEPTED);

                    const declineRes = await apiClient.declineAssignment(
                        testContract.id,
                        assignment.id,
                        staffMemberHeaders
                    );

                    validateErrorEnvelope(declineRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED
                    });

                    const finalRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
                    expect(finalAssignment.status).toBe(AssignmentStatus.ACCEPTED);
                });
            });
        });

        describe('Transition: confirm_assignment (ACCEPTED -> CONFIRMED)', () => {
            describe('P2-ASSIGN-03.1: ACCEPTED assignment successfully transitions to CONFIRMED', () => {
                it('should transition assignment from ACCEPTED to CONFIRMED', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);

                    const acceptedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const acceptedAssignment = handleApiResponse<Assignment>(acceptedRes, 200);
                    expect(acceptedAssignment.status).toBe(AssignmentStatus.ACCEPTED);

                    const confirmRes = await apiClient.confirmAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );
                    const confirmedAssignment = handleApiResponse<Assignment>(confirmRes, 200);

                    assertAssignment(confirmedAssignment);
                    expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);

                    const getRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
                    expect(retrievedAssignment.status).toBe(AssignmentStatus.CONFIRMED);
                });
            });

            describe('P2-ASSIGN-03.2: Confirming PROPOSED assignment directly fails', () => {
                it('should fail when trying to confirm a proposed assignment without accepting first', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);
                    expect(assignment.status).toBe(AssignmentStatus.PROPOSED);

                    const confirmRes = await apiClient.confirmAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(confirmRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED
                    });

                    const finalRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
                    expect(finalAssignment.status).toBe(AssignmentStatus.PROPOSED);
                });
            });
        });

        describe('Transition: cancel_assignment (PROPOSED/ACCEPTED/CONFIRMED -> CANCELLED)', () => {
            describe('P2-ASSIGN-04.1: CONFIRMED assignment successfully transitions to CANCELLED', () => {
                it('should transition assignment from CONFIRMED to CANCELLED', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const confirmedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const confirmedAssignment = handleApiResponse<Assignment>(confirmedRes, 200);
                    expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );
                    const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);

                    assertAssignment(cancelledAssignment);
                    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

                    const getRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
                    expect(retrievedAssignment.status).toBe(AssignmentStatus.CANCELLED);
                });
            });

            describe('P2-ASSIGN-04.2: Cancelling PAID assignment fails', () => {
                it('should fail when trying to cancel a paid assignment', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    await apiClient.initiatePayroll(testContract.id, coordinatorHeaders);

                    await apiClient.finalizePayroll(testContract.id, coordinatorHeaders);

                    const paidRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const paidAssignment = handleApiResponse<Assignment>(paidRes, 200);
                    expect(paidAssignment.status).toBe(AssignmentStatus.PAID);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(cancelRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
                    });

                    const finalRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
                    expect(finalAssignment.status).toBe(AssignmentStatus.PAID);
                });
            });
        });

        describe('Transition: mark_as_paid (CONFIRMED -> PAID)', () => {
            describe('P2-ASSIGN-05.1: CONFIRMED assignment implicitly transitions to PAID after payroll finalization', () => {
                it('should transition assignment from CONFIRMED to PAID when payroll is finalized', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const confirmedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const confirmedAssignment = handleApiResponse<Assignment>(confirmedRes, 200);
                    expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);

                    await apiClient.initiatePayroll(testContract.id, coordinatorHeaders);

                    const finalizeRes = await apiClient.finalizePayroll(testContract.id, coordinatorHeaders);
                    expect(finalizeRes.status).toBe(200);

                    const getRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const paidAssignment = handleApiResponse<Assignment>(getRes, 200);
                    expect(paidAssignment.status).toBe(AssignmentStatus.PAID);
                });
            });

            describe('P2-ASSIGN-05.2: ACCEPTED assignment prevents payroll initiation', () => {
                it('should fail to initiate payroll when an assignment is in ACCEPTED state', async () => {
                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(testShift.id, testStaff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);

                    const acceptedRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const acceptedAssignment = handleApiResponse<Assignment>(acceptedRes, 200);
                    expect(acceptedAssignment.status).toBe(AssignmentStatus.ACCEPTED);

                    const shift2Res = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Second Role' }),
                        coordinatorHeaders
                    );
                    const shift2 = getSuccessData<Shift>(shift2Res);

                    const staff2Res = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Second', last_name: 'Staff' }),
                        coordinatorHeaders
                    );
                    const staff2 = getSuccessData<StaffProfile>(staff2Res);

                    const assignment2Res = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift2.id, staff2.id),
                        accountManagerHeaders
                    );
                    const assignment2 = getSuccessData<Assignment>(assignment2Res);

                    await apiClient.acceptAssignment(testContract.id, assignment2.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment2.id, coordinatorHeaders);

                    const payrollRes = await apiClient.initiatePayroll(testContract.id, coordinatorHeaders);

                    validateErrorEnvelope(payrollRes, {
                        expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
                    });

                    const finalAssignmentRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
                    expect(finalAssignment.status).toBe(AssignmentStatus.ACCEPTED);

                    const contractRes = await apiClient.getContract(testContract.id, coordinatorHeaders);
                    const contract = handleApiResponse<StaffingContract>(contractRes, 200);
                    expect(contract.status).toBe(ContractStatus.ACTIVE);
                });
            });
        });
    });

    describe('Additional State Transition Edge Cases', () => {
        let contract: StaffingContract;
        let event: Event;
        let shift: Shift;
        let staff: StaffProfile;

        beforeEach(async () => {
            const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
            contract = getSuccessData<StaffingContract>(contractRes);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            contract = handleApiResponse<StaffingContract>(activateRes, 200);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            event = getSuccessData<Event>(eventRes);

            const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
            shift = getSuccessData<Shift>(shiftRes);

            const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            staff = getSuccessData<StaffProfile>(staffRes);
        });

        describe('Event Readiness', () => {
            it('should fail to mark an event as ready if it has unfilled shifts', async () => {
                const updateRes = await apiClient.updateEventStatus(
                    contract.id,
                    event.id,
                    { status: EventStatus.READY_FOR_EXECUTION },
                    coordinatorHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED,
                });
            });
        });

        describe('Assignment State Integrity', () => {
            it('should fail to accept a CANCELLED assignment', async () => {
                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = getSuccessData<Assignment>(assignmentRes);

                await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                const acceptRes = await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);

                validateErrorEnvelope(acceptRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED,
                });
            });

            it('should fail to confirm a CANCELLED assignment', async () => {
                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = getSuccessData<Assignment>(assignmentRes);

                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                const confirmRes = await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                validateErrorEnvelope(confirmRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED,
                });
            });

            it('should fail to cancel a DECLINED assignment', async () => {
                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = getSuccessData<Assignment>(assignmentRes);

                await apiClient.declineAssignment(contract.id, assignment.id, staffMemberHeaders);

                const cancelRes = await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE,
                });
            });
        });

        describe('Contract State Integrity', () => {
            it('should fail to initiate payroll if a PROPOSED assignment exists', async () => {
                await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );

                const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                validateErrorEnvelope(payrollRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST,
                });
            });

            it('should fail to activate a CLOSED contract', async () => {
                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);

                validateErrorEnvelope(activateRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_IN_PLANNING,
                });
            });

            it('should fail to finalize payroll for a CLOSED contract', async () => {
                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                validateErrorEnvelope(finalizeRes, {
                    expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_READY_FOR_PAYROLL,
                });
            });
        });
    });

    describe('Further State Transition Integrity', () => {
        let contract: StaffingContract;
        let event: Event;

        beforeEach(async () => {
            const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
            contract = getSuccessData<StaffingContract>(contractRes);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            contract = handleApiResponse<StaffingContract>(activateRes, 200);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            event = getSuccessData<Event>(eventRes);
        });

        it('should fail to mark an event with zero shifts as ready', async () => {
            const updateRes = await apiClient.updateEventStatus(
                contract.id,
                event.id,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );

            validateErrorEnvelope(updateRes, {
                expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED,
            });
        });

        it('should fail to mark an event that is already READY_FOR_EXECUTION as ready again', async () => {
            const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
            const shift = getSuccessData<Shift>(shiftRes);

            const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = getSuccessData<StaffProfile>(staffRes);

            const assignmentRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
            const assignment = getSuccessData<Assignment>(assignmentRes);

            await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

            await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.READY_FOR_EXECUTION }, coordinatorHeaders);

            const updateAgainRes = await apiClient.updateEventStatus(
                contract.id,
                event.id,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );

            validateErrorEnvelope(updateAgainRes, {
                expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION,
            });
        });

        it('should fail to propose an assignment to a CANCELLED shift', async () => {
            const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
            const shift = getSuccessData<Shift>(shiftRes);

            await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = getSuccessData<StaffProfile>(staffRes);

            const assignmentRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);

            validateErrorEnvelope(assignmentRes, {
                expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_OPEN,
            });
        });

        it('should fail to initiate payroll for a contract that is already PAYROLL_PENDING', async () => {
            await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

            const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

            validateErrorEnvelope(payrollRes, {
                expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
            });
        });

        it('should fail to initiate payroll for a CLOSED contract', async () => {
            await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
            await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

            const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

            validateErrorEnvelope(payrollRes, {
                expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
            });
        });
    });

    describe('Cross-Resource State Integrity and Scoping', () => {
        let contract1: StaffingContract;
        let contract2: StaffingContract;

        beforeEach(async () => {
            const [res1, res2] = await Promise.all([
                apiClient.createContract(createContractPayload({ client_name: 'Contract One' }), coordinatorHeaders),
                apiClient.createContract(createContractPayload({ client_name: 'Contract Two' }), coordinatorHeaders),
            ]);
            contract1 = getSuccessData<StaffingContract>(res1);
            contract2 = getSuccessData<StaffingContract>(res2);

            await Promise.all([
                apiClient.activateContract(contract1.id, coordinatorHeaders),
                apiClient.activateContract(contract2.id, coordinatorHeaders),
            ]);
        });

        it('should fail to confirm an assignment if its shift was cancelled', async () => {
            const eventRes = await apiClient.createEvent(contract1.id, createEventPayload(), coordinatorHeaders);
            const event = getSuccessData<Event>(eventRes);

            const shiftRes = await apiClient.createShift(contract1.id, event.id, createShiftPayload(), coordinatorHeaders);
            const shift = getSuccessData<Shift>(shiftRes);

            const staffRes = await apiClient.createStaffProfile(contract1.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = getSuccessData<StaffProfile>(staffRes);

            const assignmentRes = await apiClient.createAssignment(contract1.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
            const assignment = getSuccessData<Assignment>(assignmentRes);

            await apiClient.acceptAssignment(contract1.id, assignment.id, staffMemberHeaders);

            await apiClient.updateEventStatus(contract1.id, event.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

            const cancelledShiftRes = await apiClient.getShift(contract1.id, event.id, shift.id, coordinatorHeaders);
            const cancelledShift = handleApiResponse<Shift>(cancelledShiftRes, 200);
            expect(cancelledShift.status).toBe(ShiftStatus.CANCELLED);

            const cancelledAssignmentRes = await apiClient.getAssignment(contract1.id, assignment.id, coordinatorHeaders);
            const cancelledAssignment = handleApiResponse<Assignment>(cancelledAssignmentRes, 200);
            expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

            const confirmRes = await apiClient.confirmAssignment(contract1.id, assignment.id, coordinatorHeaders);

            validateErrorEnvelope(confirmRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED,
            });
        });

        it('should fail to accept an assignment using the wrong contract ID', async () => {
            const eventRes = await apiClient.createEvent(contract1.id, createEventPayload(), coordinatorHeaders);
            const event = getSuccessData<Event>(eventRes);

            const shiftRes = await apiClient.createShift(contract1.id, event.id, createShiftPayload(), coordinatorHeaders);
            const shift = getSuccessData<Shift>(shiftRes);

            const staffRes = await apiClient.createStaffProfile(contract1.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = getSuccessData<StaffProfile>(staffRes);

            const assignmentRes = await apiClient.createAssignment(contract1.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
            const assignment = getSuccessData<Assignment>(assignmentRes);

            const acceptRes = await apiClient.acceptAssignment(contract2.id, assignment.id, staffMemberHeaders);

            validateErrorEnvelope(acceptRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            });
        });

        it('should fail to finalize payroll for a contract in PLANNING state', async () => {
            const planningContractRes = await apiClient.createContract(createContractPayload({ client_name: 'Planning Only' }), coordinatorHeaders);
            const planningContract = getSuccessData<StaffingContract>(planningContractRes);

            const finalizeRes = await apiClient.finalizePayroll(planningContract.id, coordinatorHeaders);

            validateErrorEnvelope(finalizeRes, {
                expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_READY_FOR_PAYROLL,
            });
        });
    });
});
