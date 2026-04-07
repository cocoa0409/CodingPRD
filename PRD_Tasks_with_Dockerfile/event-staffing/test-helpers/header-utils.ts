import { UserRole } from './types';

export interface ApiHeaders {
  'X-User-ID': string;
  'X-User-Role': UserRole;
  [key: string]: string;
}

export function buildUserHeaders(userId: string, userRole: UserRole): ApiHeaders {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole
  };
}
