import { buildUserHeaders } from './utils';

export const TEST_USERS = {
  chargeNurseHeaders: buildUserHeaders('cn-1', 'ChargeNurse'),
  physicianHeaders: buildUserHeaders('physician-1', 'AttendingPhysician'),
  adminHeaders: buildUserHeaders('admin-1', 'HospitalAdministrator'),
} as const;
